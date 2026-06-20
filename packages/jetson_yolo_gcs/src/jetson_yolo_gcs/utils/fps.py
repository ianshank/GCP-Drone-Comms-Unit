"""Rolling FPS counter (pure; injectable clock for deterministic tests)."""

from __future__ import annotations

from collections import deque

from ..core.clock import Clock, MonotonicClock


class FpsCounter:
    """Sliding-window frames-per-second estimate.

    Call :meth:`tick` once per processed frame; :attr:`fps` (and the value returned by
    :meth:`tick`) is the rate over the last ``window`` ticks. Returns ``0.0`` until at
    least two ticks have been recorded.
    """

    def __init__(self, window: int = 30, *, clock: Clock | None = None) -> None:
        if window < 2:
            raise ValueError("window must be >= 2")
        self._clock: Clock = clock or MonotonicClock()
        self._times: deque[float] = deque(maxlen=window)

    def tick(self) -> float:
        """Record a frame at the current time and return the current FPS."""
        self._times.append(self._clock.now())
        return self.fps

    @property
    def fps(self) -> float:
        """Frames per second over the current window (``0.0`` if undefined)."""
        if len(self._times) < 2:
            return 0.0
        elapsed = self._times[-1] - self._times[0]
        if elapsed <= 0:
            return 0.0
        return (len(self._times) - 1) / elapsed
