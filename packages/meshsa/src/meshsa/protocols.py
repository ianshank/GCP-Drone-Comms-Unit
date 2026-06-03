"""Structural interfaces for dependency injection.

Everything the core needs from the outside world is a ``Protocol`` here, so the
router/node can be assembled with real or fake implementations without changes.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable


@runtime_checkable
class Transport(Protocol):
    """A bidirectional byte pipe onto some medium (radio, IP, loopback)."""

    name: str

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def send(self, data: bytes) -> None: ...
    def stream(self) -> AsyncIterator[bytes]: ...


@runtime_checkable
class Codec(Protocol):
    """Serialises Envelopes to/from bytes on the wire."""

    name: str

    def encode(self, envelope: object) -> bytes: ...
    def decode(self, data: bytes) -> object: ...


@runtime_checkable
class Clock(Protocol):
    def now(self) -> float: ...


@runtime_checkable
class IdFactory(Protocol):
    def new_id(self) -> str: ...


class SystemClock:
    """Default wall-clock implementation."""

    def now(self) -> float:
        return time.time()


class UuidFactory:
    """Default message-id source."""

    def new_id(self) -> str:
        return uuid.uuid4().hex
