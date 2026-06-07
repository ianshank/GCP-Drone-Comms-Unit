"""TAK transports: stream CoT to/from a TAK server (FreeTAKServer) over TCP with
automatic reconnect/backoff, or exchange CoT datagrams over UDP multicast.

Pair with the ``cot`` codec (per-transport) so a node bridges a JSON mesh to a
CoT/TAK link. All network I/O is behind an injected seam (``connector`` for TCP,
``io_factory`` for multicast) and the backoff ``sleep`` is injectable, so the
framing/reconnect/bridge logic is tested with fakes; only the real socket builders
are ``# pragma: no cover``. Nothing is hard-coded — host/port/group/read-size/
delimiter and the backoff schedule all come from config options.

TLS: set ``tls=True`` (plus optional ``tls_cafile`` / ``tls_certfile`` /
``tls_keyfile`` / ``tls_verify`` / ``tls_check_hostname`` / ``tls_server_hostname``)
to talk to a hardened FreeTAKServer (typically ``:8089``). When ``tls`` is enabled
and no explicit ``connector`` is injected, the TCP connector is built with an
``ssl.SSLContext`` from :func:`_build_ssl_context`. The context is built (and a bad
or missing cert raises) at construction time — fail-fast, not deferred to
``start()``. The plain ``:8087`` path is unchanged when ``tls`` is left ``False``.

Pacing: set ``pace_min_interval_s`` to enforce a minimum hold between outbound CoT
frames (PyTAK ``FTS_COMPAT`` style) so a fast telemetry source does not overrun a
rate-limited FreeTAKServer. Pacing is inline in ``send()`` (the router's send path is
already serial and blocking), disabled by default, and applies only to the TCP
server link — multicast is a fan-out group with no such rate limit.
"""

from __future__ import annotations

import asyncio
import contextlib
import ssl
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

import structlog

from ..pacing import Pacer
from ..protocols import Clock, SleepFn, SystemClock
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


def _default_connector(host: str, port: int) -> Connector:  # pragma: no cover - real network
    async def connect() -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        return await asyncio.open_connection(host, port)

    return connect


def _build_ssl_context(
    *,
    cafile: str | None = None,
    certfile: str | None = None,
    keyfile: str | None = None,
    verify: bool = True,
    check_hostname: bool = True,
) -> ssl.SSLContext:
    """Build a client TLS context for the CoT/TAK link.

    Pure (no socket): create a default client context, optionally trust ``cafile``
    and load a client cert chain (``certfile``/``keyfile``), then apply verification
    settings. When ``verify`` is False, ``check_hostname`` is cleared **before**
    setting ``CERT_NONE`` — stdlib ``ssl`` raises ``ValueError`` if hostname
    checking is left enabled with ``CERT_NONE``.
    """
    context = ssl.create_default_context(cafile=cafile)
    if certfile is not None:
        context.load_cert_chain(certfile=certfile, keyfile=keyfile)
    if verify:
        context.check_hostname = check_hostname
    else:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    return context


def _default_tls_connector(
    host: str, port: int, context: ssl.SSLContext, server_hostname: str | None
) -> Connector:  # pragma: no cover - real network
    async def connect() -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        return await asyncio.open_connection(
            host, port, ssl=context, server_hostname=server_hostname or host
        )

    return connect


class TakTcpTransport(AbstractTransport):
    def __init__(
        self,
        name: str = "tak_tcp",
        *,
        connector: Connector | None = None,
        host: str = "127.0.0.1",
        port: int = 8087,
        tls: bool = False,
        tls_cafile: str | None = None,
        tls_certfile: str | None = None,
        tls_keyfile: str | None = None,
        tls_verify: bool = True,
        tls_check_hostname: bool = True,
        tls_server_hostname: str | None = None,
        read_size: int = 4096,
        delimiter: bytes = b"",
        reconnect: bool = True,
        backoff_initial_s: float = 1.0,
        backoff_max_s: float = 30.0,
        backoff_factor: float = 2.0,
        sleep: SleepFn | None = None,
        pace_min_interval_s: float = 0.0,
        clock: Clock | None = None,
        queue_maxsize: int = 1000,
        **_: Any,
    ) -> None:
        super().__init__(name, queue_maxsize)
        # An injected connector always wins (tests, or a custom TLS override). Else,
        # when tls is requested, build a TLS connector (the SSL context is validated
        # now — fail-fast). Otherwise fall back to the plaintext connector.
        if connector is not None:
            self._connector = connector
        elif tls:
            context = _build_ssl_context(
                cafile=tls_cafile,
                certfile=tls_certfile,
                keyfile=tls_keyfile,
                verify=tls_verify,
                check_hostname=tls_check_hostname,
            )
            self._connector = _default_tls_connector(host, port, context, tls_server_hostname)
        else:
            self._connector = _default_connector(host, port)
        self._read_size = read_size
        self._delimiter = delimiter
        self._reconnect = reconnect
        self._backoff_initial = backoff_initial_s
        self._backoff_max = backoff_max_s
        self._backoff_factor = backoff_factor
        self._sleep = sleep or asyncio.sleep
        # Optional outbound pacing (minimum-hold) so a fast source does not overrun a
        # rate-limited FTS. Disabled by default -> send() is byte-for-byte unchanged.
        self._pacer = (
            Pacer(
                min_interval_s=pace_min_interval_s,
                clock=clock or SystemClock(),
                sleep=self._sleep,
            )
            if pace_min_interval_s > 0
            else None
        )
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._task: asyncio.Task[None] | None = None
        self._started = False
        self._stopping = False
        #: Times the supervisor (re)established the connection (observability).
        self.reconnects = 0

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
                self.reconnects += 1
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
        if self._pacer is not None:
            await self._pacer.wait()  # minimum-hold so a fast source doesn't overrun FTS
        try:
            writer.write(data + self._delimiter)
            await writer.drain()
        except Exception:
            _log.warning("tak_tcp send failed; dropping frame", transport=self.name)

    async def stop(self) -> None:
        self._stopping = True
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
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
        self._task: asyncio.Task[None] | None = None

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
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
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
