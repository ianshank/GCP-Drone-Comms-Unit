"""Reusable send pacer (token bucket) for rate-limiting a transport's outbound.

Sits beside :mod:`meshsa.transports.backoff`: one small policy class with an
injected :class:`~meshsa.protocols.Clock` and async ``sleep`` (the shared
:data:`~meshsa.transports.backoff.SleepFn`), so the timing math is unit-tested
deterministically with a fake clock and no real waiting. Used to keep a fast
track stream from overrunning a rate-sensitive sink (e.g. FreeTAKServer); pacing
is opt-in per transport via config, never on by default.
"""

from __future__ import annotations

import asyncio

from ..protocols import Clock, SystemClock
from .backoff import SleepFn


class Pacer:
    """Token-bucket pacer: caps the sustained send rate while allowing a burst.

    :meth:`acquire` returns at once while tokens remain (up to ``burst``);
    otherwise it awaits just long enough for one token to refill at ``rate_hz``.
    The clock and sleep are injected so tests assert the delay schedule with a
    fake clock and a recording sleep — no real time passes.
    """

    def __init__(
        self,
        *,
        rate_hz: float,
        burst: int = 1,
        clock: Clock | None = None,
        sleep: SleepFn | None = None,
    ) -> None:
        if rate_hz <= 0:
            raise ValueError("rate_hz must be positive")
        if burst < 1:
            raise ValueError("burst must be >= 1")
        self._interval = 1.0 / rate_hz
        self._capacity = float(burst)
        self._clock: Clock = clock or SystemClock()
        self._sleep: SleepFn = sleep or asyncio.sleep
        self._tokens = float(burst)
        self._last = self._clock.now()

    async def acquire(self) -> None:
        """Consume one token, waiting for a refill if the bucket is empty."""
        now = self._clock.now()
        # Refill for the elapsed interval, capped at capacity.
        self._tokens = min(self._capacity, self._tokens + (now - self._last) / self._interval)
        self._last = now
        if self._tokens < 1.0:
            await self._sleep((1.0 - self._tokens) * self._interval)
            # Exactly one token's worth of time has now elapsed; consume it.
            self._tokens = 0.0
            self._last = self._clock.now()
        else:
            self._tokens -= 1.0
