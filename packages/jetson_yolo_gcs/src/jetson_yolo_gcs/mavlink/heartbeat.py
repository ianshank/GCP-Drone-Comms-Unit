"""Autopilot-heartbeat freshness gate for the ``LANDING_TARGET`` publisher.

Mirrors ``meshsa.command.health.HeartbeatHealth`` **without importing meshsa** — this
package is self-contained (no meshsa runtime dependency). The monitor is fed the
autopilot's MAVLink ``HEARTBEAT`` timestamps and reports whether they are *fresh*, so the
precision-landing publisher can **fail closed** (suppress) when the autopilot link is
silent. It is intentionally conservative: link-liveness only, no SYS_STATUS/EKF/GPS gating.

The freshness timebase is monotonic by default (``MonotonicClock``) — it measures elapsed
time and is immune to wall-clock jumps (NTP steps, DST). That is deliberately distinct from
the wall clock the bridge uses for the ``LANDING_TARGET`` ``time_usec`` field.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog

from ..core.clock import Clock, MonotonicClock

_log = structlog.get_logger("jetson_yolo_gcs.mavlink.heartbeat")


@dataclass(frozen=True)
class HeartbeatReport:
    """Immutable freshness snapshot from :class:`HeartbeatMonitor`."""

    #: True only when a heartbeat has been seen and it is within the freshness window.
    fresh: bool
    #: Fail-closed reason codes: ``("no_heartbeat",)`` before the first beat,
    #: ``("heartbeat_stale",)`` once the last beat has aged out; empty when fresh.
    reasons: tuple[str, ...]
    #: Timebase timestamp of the most recent beat (``None`` until the first beat).
    last_beat_t: float | None


class HeartbeatMonitor:
    """Tracks autopilot heartbeat freshness on an injected clock (fail-closed)."""

    def __init__(self, clock: Clock | None = None, *, max_age_s: float) -> None:
        self._clock: Clock = clock or MonotonicClock()
        self._max_age_s = max_age_s
        self._last: float | None = None

    def beat(self, t: float | None = None) -> None:
        """Record a heartbeat at ``t`` (default: now), on the clock's timebase."""
        first = self._last is None
        self._last = self._clock.now() if t is None else t
        if first:
            _log.debug("autopilot heartbeat acquired", t=self._last)

    def report(self, now: float | None = None) -> HeartbeatReport:
        """Return the current freshness :class:`HeartbeatReport` (pure; fail-closed)."""
        if self._last is None:
            return HeartbeatReport(fresh=False, reasons=("no_heartbeat",), last_beat_t=None)
        t = self._clock.now() if now is None else now
        fresh = (t - self._last) <= self._max_age_s
        return HeartbeatReport(
            fresh=fresh,
            reasons=() if fresh else ("heartbeat_stale",),
            last_beat_t=self._last,
        )

    def is_fresh(self, now: float | None = None) -> bool:
        """Convenience: ``True`` only when a heartbeat has been seen recently enough."""
        return self.report(now).fresh
