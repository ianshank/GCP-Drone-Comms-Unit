"""TAK UDP multicast transport: exchange CoT datagrams over a multicast group.

Split out of ``tak.py`` (code-hygiene-modularity T-4.2) — it shares no code with
the TCP transport (``tak.py::TakTcpTransport``) beyond the
``Transport``/``AbstractTransport`` contract; the two lived in one file only
because both speak CoT/TAK. All network I/O is behind an injected ``io_factory``
seam and the backoff ``sleep`` is injectable, so the reconnect/ingest logic is
tested with fakes; only the real socket builder is ``# pragma: no cover``.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from typing import Any, Protocol

import structlog

from ..defaults import (
    DEFAULT_BACKOFF_FACTOR,
    DEFAULT_BACKOFF_INITIAL_S,
    DEFAULT_BACKOFF_MAX_S,
    DEFAULT_MULTICAST_IFACE,
    DEFAULT_QUEUE_MAXSIZE,
    DEFAULT_TAK_MULTICAST_GROUP,
    PORT_TAK_MULTICAST,
)
from ..registry import transport_registry
from .backoff import Backoff, SleepFn
from .base import AbstractTransport

_log = structlog.get_logger("meshsa.tak")


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
        group: str = DEFAULT_TAK_MULTICAST_GROUP,
        port: int = PORT_TAK_MULTICAST,
        iface: str = DEFAULT_MULTICAST_IFACE,
        backoff_initial_s: float = DEFAULT_BACKOFF_INITIAL_S,
        backoff_max_s: float = DEFAULT_BACKOFF_MAX_S,
        backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
        sleep: SleepFn | None = None,
        queue_maxsize: int = DEFAULT_QUEUE_MAXSIZE,
        **_: Any,
    ) -> None:
        super().__init__(name, queue_maxsize)
        self._port = int(port)
        self._io_factory = io_factory or (lambda: _default_multicast_io(group, self._port, iface))
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


@transport_registry.register("tak_multicast")
def _make_tak_multicast(name: str = "tak_multicast", **options: Any) -> TakMulticastTransport:
    return TakMulticastTransport(name=name, **options)
