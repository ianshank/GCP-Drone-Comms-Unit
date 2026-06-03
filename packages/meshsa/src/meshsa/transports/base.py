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

    async def _ingest(self, data: bytes) -> None:
        """Called by the concrete transport when bytes arrive from the medium.

        Non-blocking: when the inbox is full (a slow subscriber), the newest
        frame is dropped and counted rather than stalling the reader — matching
        the transports' best-effort delivery model on a lossy medium. The inbox
        bound is ``queue_maxsize`` (configurable via ``RouterConfig``).
        """
        try:
            self._inbox.put_nowait(data)
        except asyncio.QueueFull:
            self.dropped_inbox_full += 1
            _log.warning("inbox full; dropping frame", transport=self.name)

    async def stream(self) -> AsyncIterator[bytes]:
        while True:
            yield await self._inbox.get()

    @abc.abstractmethod
    async def send(self, data: bytes) -> None:  # pragma: no cover - abstract
        raise NotImplementedError
