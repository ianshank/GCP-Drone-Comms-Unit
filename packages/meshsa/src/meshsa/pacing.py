"""Outbound rate pacing (minimum-hold), config-driven and dependency-injected.

A :class:`Pacer` enforces a minimum interval between successive actions — the same
contract as PyTAK's ``FTS_COMPAT`` — so a fast telemetry source does not overrun a
rate-limited sink (e.g. FreeTAKServer, which silently drops tracks that arrive too
quickly). It is pure and deterministic: the clock and sleep are injected, so pacing
is unit-tested without real wall-clock time.
"""

from __future__ import annotations

from .protocols import Clock, SleepFn


class Pacer:
    """Minimum-hold pacer.

    ``wait()`` blocks until at least ``min_interval_s`` has elapsed since the
    previous call returned; the first call never waits. The post-sleep clock value
    is used as the new reference so drift does not accumulate.
    """

    def __init__(self, *, min_interval_s: float, clock: Clock, sleep: SleepFn) -> None:
        self._min_interval = min_interval_s
        self._clock = clock
        self._sleep = sleep
        self._last: float | None = None

    async def wait(self) -> None:
        now = self._clock.now()
        if self._last is not None:
            delay = self._min_interval - (now - self._last)
            if delay > 0:
                await self._sleep(delay)
                now = self._clock.now()
        self._last = now
