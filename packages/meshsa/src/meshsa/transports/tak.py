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
import contextlib
import ssl
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

import structlog

from ..registry import transport_registry
from .backoff import Backoff, SleepFn
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

#: Default CoT ports: plaintext (FreeTAKServer default) and TLS.
_DEFAULT_PLAINTEXT_PORT = 8087
_DEFAULT_TLS_PORT = 8089


def _resolve_tak_endpoint(host: str, port: int | None, tls: bool) -> tuple[str, int, bool]:
    """Resolve ``(host, port, tls)`` from a possibly-schemed host + optional port.

    Accepts a bare host or a PyTAK-style ``tls://``/``ssl://``/``tcp://`` URL; a
    scheme sets TLS, otherwise the ``tls`` flag decides. Port defaults to 8089 for
    TLS and 8087 for plaintext when not given explicitly or embedded in the host.
    Pure (no I/O) so the scheme/port logic is unit-tested without a socket.
    """
    use_tls = tls
    embedded_port: int | None = None
    if "://" in host:
        scheme, _, host = host.partition("://")
        use_tls = scheme.lower() in ("tls", "ssl")
    if host.count(":") == 1:  # host:port (IPv6 literals are out of scope here)
        host, _, port_str = host.partition(":")
        embedded_port = int(port_str)
    resolved = port if port is not None else embedded_port
    if resolved is None:
        resolved = _DEFAULT_TLS_PORT if use_tls else _DEFAULT_PLAINTEXT_PORT
    return host, resolved, use_tls


def _build_ssl_context(  # pragma: no cover - real TLS / cert file I/O
    *, ca_cert: str | None, client_cert: str | None, client_key: str | None, verify: bool
) -> ssl.SSLContext:
    """Build a client-side TLS context. Real-cert glue (covered on deploy, not CI)."""
    ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=ca_cert)
    if not verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    if client_cert is not None:
        ctx.load_cert_chain(certfile=client_cert, keyfile=client_key)
    return ctx


def _default_connector(  # pragma: no cover - real network
    host: str,
    port: int,
    *,
    ssl_context: ssl.SSLContext | None = None,
    server_hostname: str | None = None,
) -> Connector:
    async def connect() -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        if ssl_context is not None:
            return await asyncio.open_connection(
                host, port, ssl=ssl_context, server_hostname=server_hostname or host
            )
        return await asyncio.open_connection(host, port)

    return connect


class TakTcpTransport(AbstractTransport):
    def __init__(
        self,
        name: str = "tak_tcp",
        *,
        connector: Connector | None = None,
        host: str = "127.0.0.1",
        port: int | None = None,
        tls: bool = False,
        tls_ca_cert: str | None = None,
        tls_client_cert: str | None = None,
        tls_client_key: str | None = None,
        tls_verify: bool = True,
        tls_server_hostname: str | None = None,
        ssl_context_factory: Callable[[], ssl.SSLContext] | None = None,
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
        host, resolved_port, use_tls = _resolve_tak_endpoint(host, port, tls)
        #: Resolved endpoint (exposed for observability/tests). Plaintext stays the
        #: default (8087); TLS targets 8089 unless an explicit port is given.
        self.host = host
        self.port = resolved_port
        self.tls = use_tls
        #: The TLS context in use, or None for plaintext (exposed for tests).
        self._ssl_context: ssl.SSLContext | None = None
        if connector is not None:
            self._connector = connector
        else:
            if use_tls:
                if ssl_context_factory is not None:
                    self._ssl_context = ssl_context_factory()
                else:  # pragma: no cover - real TLS context (needs certs on deploy)
                    self._ssl_context = _build_ssl_context(
                        ca_cert=tls_ca_cert,
                        client_cert=tls_client_cert,
                        client_key=tls_client_key,
                        verify=tls_verify,
                    )
            self._connector = _default_connector(
                host,
                resolved_port,
                ssl_context=self._ssl_context,
                server_hostname=tls_server_hostname,
            )
        self._read_size = read_size
        self._delimiter = delimiter
        self._reconnect = reconnect
        self._backoff = Backoff(
            initial_s=backoff_initial_s, max_s=backoff_max_s, factor=backoff_factor, sleep=sleep
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
        self._backoff.reset()
        while not self._stopping:
            if self._reader is None:
                try:
                    self._reader, self._writer = await self._connector()
                except Exception:
                    _log.warning("tak_tcp connect failed", transport=self.name)
                    await self._backoff.sleep_and_advance()
                    continue
                self._backoff.reset()
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
            await self._backoff.sleep_and_advance()

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
        backoff_initial_s: float = 1.0,
        backoff_max_s: float = 30.0,
        backoff_factor: float = 2.0,
        sleep: SleepFn | None = None,
        queue_maxsize: int = 1000,
        **_: Any,
    ) -> None:
        super().__init__(name, queue_maxsize)
        self._io_factory = io_factory or (lambda: _default_multicast_io(group, port, iface))
        self._io: DatagramIO | None = None
        self._task: asyncio.Task[None] | None = None
        self._stopping = False
        self._backoff = Backoff(
            initial_s=backoff_initial_s, max_s=backoff_max_s, factor=backoff_factor, sleep=sleep
        )
        #: Times the recv loop rebuilt the socket after an error (observability).
        self.reconnects = 0

    async def start(self) -> None:
        await super().start()
        self._stopping = False
        self._io = self._io_factory()
        self._task = asyncio.create_task(self._recv_loop())

    async def _recv_loop(self) -> None:
        # Mirror the TCP supervisor: a transient recv error must not permanently
        # kill multicast ingestion. On error, close the wedged socket, back off,
        # and rebuild it. The rebuild is guarded too — if the interface is still
        # hard-down, ``_io_factory`` (socket bind + IP_ADD_MEMBERSHIP) raises, and
        # an unguarded rebuild would kill this task forever; instead we log, back
        # off, and retry the factory on the next pass so ingestion self-heals once
        # the interface returns.
        self._backoff.reset()
        while not self._stopping:
            if self._io is None:
                try:
                    self._io = self._io_factory()
                except Exception:
                    _log.warning("tak_multicast rebuild failed; retrying", transport=self.name)
                    await self._backoff.sleep_and_advance()
                    continue
                self._backoff.reset()
                self.reconnects += 1
            try:
                data = await self._io.recv()
                if data:
                    await self._ingest(data)
                self._backoff.reset()
            except Exception:
                _log.warning("tak_multicast recv error; rebuilding", transport=self.name)
                self._close_io()
                await self._backoff.sleep_and_advance()

    def _close_io(self) -> None:
        io, self._io = self._io, None
        if io is None:
            return
        try:
            io.close()
        except Exception:  # best-effort during error recovery / shutdown
            _log.debug("tak_multicast io close error", transport=self.name)

    async def send(self, data: bytes) -> None:
        if self._io is None:
            raise RuntimeError("transport not started")
        self._io.sendto(data)

    async def stop(self) -> None:
        self._stopping = True
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        self._close_io()
        await super().stop()


@transport_registry.register("tak_tcp")
def _make_tak_tcp(name: str = "tak_tcp", **options: Any) -> TakTcpTransport:
    return TakTcpTransport(name=name, **options)


@transport_registry.register("tak_multicast")
def _make_tak_multicast(name: str = "tak_multicast", **options: Any) -> TakMulticastTransport:
    return TakMulticastTransport(name=name, **options)
