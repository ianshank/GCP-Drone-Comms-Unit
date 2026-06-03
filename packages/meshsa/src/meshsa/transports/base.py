"""Shared transport plumbing: an inbound queue plus an async ``stream``."""

from __future__ import annotations

import abc
import asyncio
from collections.abc import AsyncIterator

import structlog

_log = structlog.get_logger("meshsa.transport")


class AbstractTransport(abc.ABC):
    def __init__(self, name: str, queue_maxsize: int = 1000) -> None:
        self.name = name
        self._inbox: asyncio.Queue[bytes] = asyncio.Queue(maxsize=queue_maxsize)
        self._running = False
        #: Frames dropped because the inbox was full (slow consumer / backpressure).
        self.dropped_inbox_full = 0

    async def start(self) -> None:
        self._running = True

    async def stop(self) -> None:
        self._running = False

    def _ingest_nowait(self, data: bytes) -> None:
        """Non-blocking, thread-safe enqueue used by every inbound path.

        When the inbox is full (a slow subscriber), the *newest* frame is dropped
        and counted rather than stalling the reader — matching the transports'
        best-effort model on a lossy medium. We drop the newest (rather than
        evicting the oldest) so a frame already accepted for in-order delivery is
        never discarded; sustained overflow signals a stuck consumer regardless.
        Safe to hand to ``loop.call_soon_threadsafe`` from a radio reader thread.
        The inbox bound is ``queue_maxsize`` (configurable via ``RouterConfig``).
        """
        try:
            self._inbox.put_nowait(data)
        except asyncio.QueueFull:
            self.dropped_inbox_full += 1
            _log.warning("inbox full; dropping frame", transport=self.name)

    async def _ingest(self, data: bytes) -> None:
        """Async ingest for in-loop callers (e.g. the TAK read loop)."""
        self._ingest_nowait(data)

    async def stream(self) -> AsyncIterator[bytes]:
        while True:
            yield await self._inbox.get()

    @abc.abstractmethod
    async def send(self, data: bytes) -> None:  # pragma: no cover - abstract
        raise NotImplementedError
