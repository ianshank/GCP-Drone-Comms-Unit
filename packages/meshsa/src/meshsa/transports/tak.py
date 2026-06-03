"""TAK transports: stream CoT to/from a TAK server (FreeTAKServer) over TCP with
automatic reconnect/backoff, or exchange CoT datagrams over UDP multicast.

Pair with the ``cot`` codec (per-transport) so a node bridges a JSON mesh to a
CoT/TAK link. All network I/O is behind an injected seam (``connector`` for TCP,
``io_factory`` for multicast) and the backoff ``sleep`` is injectable, so the
framing/reconnect/bridge logic is tested with fakes; only the real socket builders
are ``# pragma: no cover``. Nothing is hard-coded — host/port/group/read-size/
delimiter and the backoff schedule all come from config options.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

import structlog

from ..registry import transport_registry
from .base import AbstractTransport

_log = structlog.get_logger("meshsa.tak")

_EVENT_END = b"</event>"
_EVENT_START = b"<event"


class CotFramer:
    """Splits a CoT byte stream into complete ``<event>...</event>`` documents."""

    def __init__(self) -> None:
        self._buf = b""

    def feed(self, chunk: bytes) -> list[bytes]:
        self._buf += chunk
        events: list[bytes] = []
        while True:
            idx = self._buf.find(_EVENT_END)
            if idx == -1:
                break
            end = idx + len(_EVENT_END)
            raw, self._buf = self._buf[:end], self._buf[end:]
            start = raw.find(_EVENT_START)
            if start != -1:
                events.append(raw[start:])
        return events


Connector = Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]]
SleepFn = Callable[[float], Awaitable[None]]


def _default_connector(host: str, port: int) -> Connector:  # pragma: no cover - real network
    async def connect() -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        return await asyncio.open_connection(host, port)

    return connect


class TakTcpTransport(AbstractTransport):
    def __init__(
        self,
        name: str = "tak_tcp",
        *,
        connector: Connector | None = None,
        host: str = "127.0.0.1",
        port: int = 8087,
        read_size: int = 4096,
        delimiter: bytes = b"",
        reconnect: bool = True,
        backoff_initial_s: float = 1.0,
        backoff_max_s: float = 30.0,
        backoff_factor: float = 2.0,
        sleep: SleepFn | None = None,
        queue_maxsize: int = 1000,
        **_: Any,
    ) -> None:
        super().__init__(name, queue_maxsize)
        self._connector = connector or _default_connector(host, port)
        self._read_size = read_size
        self._delimiter = delimiter
        self._reconnect = reconnect
        self._backoff_initial = backoff_initial_s
        self._backoff_max = backoff_max_s
        self._backoff_factor = backoff_factor
        self._sleep = sleep or asyncio.sleep
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._task: asyncio.Task | None = None
        self._started = False
        self._stopping = False

    async def start(self) -> None:
        await super().start()
        self._started = True
        self._stopping = False
        # Establish the first connection before returning so sends work at once.
        try:
            self._reader, self._writer = await self._connector()
        except Exception:
            _log.warning("tak_tcp initial connect failed", transport=self.name)
            if not self._reconnect:
                self._started = False
                raise
            self._reader = self._writer = None
        self._task = asyncio.create_task(self._supervise())

    async def _supervise(self) -> None:
        backoff = self._backoff_initial
        while not self._stopping:
            if self._reader is None:
                try:
                    self._reader, self._writer = await self._connector()
                except Exception:
                    _log.warning("tak_tcp connect failed", transport=self.name)
                    await self._sleep(backoff)
                    backoff = min(backoff * self._backoff_factor, self._backoff_max)
                    continue
                backoff = self._backoff_initial
            try:
                await self._read_loop(self._reader)
            except Exception:
                _log.warning("tak_tcp read error", transport=self.name)
            finally:
                await self._aclose_writer()
                self._reader = None
            if not self._reconnect:
                break
            await self._sleep(backoff)
            backoff = min(backoff * self._backoff_factor, self._backoff_max)

    async def _read_loop(self, reader: asyncio.StreamReader) -> None:
        framer = CotFramer()
        while True:
            chunk = await reader.read(self._read_size)
            if not chunk:  # EOF / peer closed
                break
            for event in framer.feed(chunk):
                await self._ingest(event)

    async def _aclose_writer(self) -> None:
        writer, self._writer = self._writer, None
        if writer is None:
            return
        try:
            writer.close()
            waiter = getattr(writer, "wait_closed", None)
            if waiter is not None:
                await waiter()
        except Exception:  # best-effort during shutdown / reconnect
            _log.debug("tak_tcp writer close error", transport=self.name)

    async def send(self, data: bytes) -> None:
        if not self._started:
            raise RuntimeError("transport not started")
        writer = self._writer
        if writer is None:
            return  # transiently disconnected; best-effort drop
        try:
            writer.write(data + self._delimiter)
            await writer.drain()
        except Exception:
            _log.warning("tak_tcp send failed; dropping frame", transport=self.name)

    async def stop(self) -> None:
        self._stopping = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        await self._aclose_writer()
        self._started = False
        await super().stop()


class DatagramIO(Protocol):
    def sendto(self, data: bytes) -> None: ...
    async def recv(self) -> bytes: ...
    def close(self) -> None: ...


def _default_multicast_io(
    group: str, port: int, iface: str
) -> DatagramIO:  # pragma: no cover - real socket
    import socket

    class _MIO:
        def __init__(self) -> None:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("", port))
            mreq = socket.inet_aton(group) + socket.inet_aton(iface)
            s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            s.setblocking(False)
            self._s = s
            self._group = (group, port)

        def sendto(self, data: bytes) -> None:
            self._s.sendto(data, self._group)

        async def recv(self) -> bytes:
            loop = asyncio.get_running_loop()
            return await loop.sock_recv(self._s, 65535)

        def close(self) -> None:
            self._s.close()

    return _MIO()


class TakMulticastTransport(AbstractTransport):
    def __init__(
        self,
        name: str = "tak_multicast",
        *,
        io_factory: Callable[[], DatagramIO] | None = None,
        group: str = "239.2.3.1",
        port: int = 6969,
        iface: str = "0.0.0.0",
        queue_maxsize: int = 1000,
        **_: Any,
    ) -> None:
        super().__init__(name, queue_maxsize)
        self._io_factory = io_factory or (lambda: _default_multicast_io(group, port, iface))
        self._io: DatagramIO | None = None
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        await super().start()
        self._io = self._io_factory()
        self._task = asyncio.create_task(self._recv_loop())

    async def _recv_loop(self) -> None:
        assert self._io is not None
        while True:
            data = await self._io.recv()
            if data:
                await self._ingest(data)

    async def send(self, data: bytes) -> None:
        if self._io is None:
            raise RuntimeError("transport not started")
        self._io.sendto(data)

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._io is not None:
            self._io.close()
            self._io = None
        await super().stop()


@transport_registry.register("tak_tcp")
def _make_tak_tcp(name: str = "tak_tcp", **options: Any) -> TakTcpTransport:
    return TakTcpTransport(name=name, **options)


@transport_registry.register("tak_multicast")
def _make_tak_multicast(name: str = "tak_multicast", **options: Any) -> TakMulticastTransport:
    return TakMulticastTransport(name=name, **options)
