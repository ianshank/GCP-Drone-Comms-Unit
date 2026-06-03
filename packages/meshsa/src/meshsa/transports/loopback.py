"""In-process transports for single-host bridging and hermetic tests.

A :class:`LoopbackBus` models a shared medium: every attached transport hears
others' sends but not its own echo (so the router's dedupe is what prevents
loops, exactly as on a real mesh)."""
from __future__ import annotations

from ..registry import transport_registry
from .base import AbstractTransport


class LoopbackBus:
    def __init__(self) -> None:
        self._members: list["LoopbackTransport"] = []

    def attach(self, transport: "LoopbackTransport") -> None:
        self._members.append(transport)

    async def broadcast(self, sender: "LoopbackTransport", data: bytes) -> None:
        for member in self._members:
            if member is not sender:
                await member._ingest(data)


class LoopbackTransport(AbstractTransport):
    def __init__(self, name: str = "loopback", bus: LoopbackBus | None = None,
                 queue_maxsize: int = 1000) -> None:
        super().__init__(name, queue_maxsize)
        self.bus = bus or LoopbackBus()
        self.bus.attach(self)
        self.sent: list[bytes] = []

    async def send(self, data: bytes) -> None:
        self.sent.append(data)
        await self.bus.broadcast(self, data)


class NullTransport(AbstractTransport):
    """Drops everything; useful as a disabled placeholder."""

    async def send(self, data: bytes) -> None:
        return None


@transport_registry.register("loopback")
def _make_loopback(name: str = "loopback", bus: LoopbackBus | None = None,
                   queue_maxsize: int = 1000, **_: object) -> LoopbackTransport:
    return LoopbackTransport(name=name, bus=bus, queue_maxsize=queue_maxsize)


@transport_registry.register("null")
def _make_null(name: str = "null", queue_maxsize: int = 1000, **_: object) -> NullTransport:
    return NullTransport(name=name, queue_maxsize=queue_maxsize)
