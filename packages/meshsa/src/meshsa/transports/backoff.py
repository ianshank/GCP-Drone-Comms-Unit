"""Shared exponential reconnect backoff for the networked transports.

Encapsulates the ``initial -> min(current * factor, max)`` schedule and the
injectable async ``sleep`` that ``TakTcpTransport`` and ``MeshtasticTransport``
both drive in their reconnect supervisors, so the policy lives in exactly one
place. ``current`` starts at ``initial``; :meth:`sleep_and_advance` sleeps the
current delay then grows it (capped at ``max``); :meth:`reset` returns to
``initial`` after a successful (re)connect.

The ``sleep`` seam is injectable so reconnect/backoff is unit-tested with a fake
that records the delay sequence — no real waiting, no sockets.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

#: An awaitable sleep, e.g. ``asyncio.sleep`` or a test fake recording delays.
SleepFn = Callable[[float], Awaitable[None]]


class Backoff:
    """Exponential backoff schedule with an injectable async ``sleep``."""

    def __init__(
        self,
        *,
        initial_s: float,
        max_s: float,
        factor: float,
        sleep: SleepFn | None = None,
    ) -> None:
        self._initial = initial_s
        self._max = max_s
        self._factor = factor
        self._sleep = sleep or asyncio.sleep
        #: Current delay (seconds); read-only from the caller's perspective.
        self.current = initial_s

    def reset(self) -> None:
        """Return the delay to ``initial`` (call after a successful connect)."""
        self.current = self._initial

    async def sleep_and_advance(self) -> None:
        """Sleep for the current delay, then grow it (capped at ``max``)."""
        await self._sleep(self.current)
        self.current = min(self.current * self._factor, self._max)
