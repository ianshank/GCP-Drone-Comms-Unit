"""Transport-agnostic message router / bridge.

Responsibilities:
  * publish locally-originated envelopes to all transports,
  * pump each transport, dedupe by ``msg_id`` (loop/echo prevention),
  * forward (bridge) traffic between transports, **re-encoding per target** so a
    JSON mesh and a CoT/TAK link can interoperate through one node,
  * deliver inbound envelopes to subscribers.

All collaborators are injected, so it is fully testable without a network.
Backward compatible: with no ``codecs`` map every transport uses the single
default codec, exactly as before.
"""

from __future__ import annotations

import asyncio
import collections
import inspect
from collections.abc import Awaitable, Callable

import structlog

from .config import RouterConfig
from .models import Envelope
from .protocols import Clock, Codec, IdFactory, SystemClock, Transport, UuidFactory

Handler = Callable[[Envelope], Awaitable[None] | None]
_log = structlog.get_logger("meshsa.router")


async def _maybe_await(result: Awaitable[None] | None) -> None:
    if inspect.isawaitable(result):
        await result


class Router:
    def __init__(
        self,
        transports: list[Transport],
        codec: Codec,
        *,
        clock: Clock | None = None,
        id_factory: IdFactory | None = None,
        config: RouterConfig | None = None,
        codecs: dict[str, Codec] | None = None,
    ) -> None:
        self.transports = list(transports)
        self.codec = codec
        self.codecs = dict(codecs or {})
        self.clock = clock or SystemClock()
        self.id_factory = id_factory or UuidFactory()
        self.config = config or RouterConfig()
        self._seen: collections.OrderedDict[str, bool] = collections.OrderedDict()
        self._subscribers: list[Handler] = []
        self._tasks: list[asyncio.Task[None]] = []

    def _codec_for(self, transport: Transport) -> Codec:
        return self.codecs.get(transport.name, self.codec)

    def subscribe(self, handler: Handler) -> None:
        self._subscribers.append(handler)

    def _mark_seen(self, msg_id: str) -> bool:
        """Record ``msg_id``; return True if newly seen, False if duplicate."""
        if msg_id in self._seen:
            return False
        self._seen[msg_id] = True
        while len(self._seen) > self.config.dedupe_cache_size:
            self._seen.popitem(last=False)
        return True

    async def publish(self, envelope: Envelope) -> None:
        self._mark_seen(envelope.msg_id)
        for transport in self.transports:
            await transport.send(self._codec_for(transport).encode(envelope))

    async def start(self) -> None:
        for transport in self.transports:
            await transport.start()
        for transport in self.transports:
            self._tasks.append(asyncio.create_task(self._pump(transport)))

    async def _pump(self, source: Transport) -> None:
        src_codec = self._codec_for(source)
        async for data in source.stream():
            try:
                envelope = src_codec.decode(data)
            except Exception:  # drop malformed/incompatible frames
                _log.warning("dropped undecodable frame", transport=source.name)
                continue
            if not self._mark_seen(envelope.msg_id):
                continue
            for handler in list(self._subscribers):
                await _maybe_await(handler(envelope))
            for transport in self.transports:
                if transport is not source:
                    await transport.send(self._codec_for(transport).encode(envelope))

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks.clear()
        for transport in self.transports:
            await transport.stop()
