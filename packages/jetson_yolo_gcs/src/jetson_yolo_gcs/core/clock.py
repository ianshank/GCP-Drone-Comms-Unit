"""Clock seam for dependency injection.

Mirrors ``meshsa.protocols``: a ``@runtime_checkable`` :class:`Clock` Protocol plus
the wall-clock and monotonic implementations. Injecting a clock keeps timestamp and
rate logic deterministic under test (tests pass a fake instead of patching time).
"""

from __future__ import annotations

import time
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    """A source of monotonically-or-wall time in float seconds."""

    def now(self) -> float: ...


class SystemClock:
    """Wall-clock time (``time.time``); use for absolute/epoch timestamps."""

    def now(self) -> float:
        return time.time()


class MonotonicClock:
    """Monotonic time (``time.monotonic``).

    Immune to wall-clock jumps (NTP steps, DST), so it is the right timebase for
    elapsed-time measurements such as the FPS counter.
    """

    def now(self) -> float:
        return time.monotonic()
