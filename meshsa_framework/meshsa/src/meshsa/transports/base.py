"""Shared transport plumbing: an inbound queue plus an async ``stream``."""
from __future__ import annotations

import abc
import asyncio
from typing import AsyncIterator


class AbstractTransport(abc.ABC):
    def __init__(self, name: str, queue_maxsize: int = 1000) -> None:
        self.name = name
        self._inbox: asyncio.Queue[bytes] = asyncio.Queue(maxsize=queue_maxsize)
        self._running = False

    async def start(self) -> None:
        self._running = True

    async def stop(self) -> None:
        self._running = False

    async def _ingest(self, data: bytes) -> None:
        """Called by the concrete transport when bytes arrive from the medium."""
        await self._inbox.put(data)

    async def stream(self) -> AsyncIterator[bytes]:
        while True:
            yield await self._inbox.get()

    @abc.abstractmethod
    async def send(self, data: bytes) -> None:  # pragma: no cover - abstract
        raise NotImplementedError
