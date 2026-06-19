"""A heartbeat-driven health provider for the pre-arm interlock.

The :class:`~meshsa.command.service.CommandService` arm interlock needs a
``HealthProvider`` — a callable returning the latest :class:`HealthReport` (or
``None``). :class:`HeartbeatHealth` is the minimal real provider: it is fed the
autopilot's MAVLink HEARTBEAT timestamps and reports ``arm_permitted`` only while
heartbeats are fresh, so arming fails closed when the link is silent.

This is intentionally conservative (link-liveness only). A richer provider would
also gate on SYS_STATUS / EKF / GPS flags; that can replace this without touching
the service (it only depends on the ``HealthProvider`` callable shape).
"""

from __future__ import annotations

from ..fpv.link_health import HealthReport, HealthState
from ..protocols import Clock


class HeartbeatHealth:
    """Reports arm-permitting health while autopilot heartbeats stay fresh."""

    def __init__(self, clock: Clock, *, max_age_s: float = 3.0) -> None:
        self._clock = clock
        self._max_age_s = max_age_s
        self._last: float | None = None

    def beat(self, t: float | None = None) -> None:
        """Record a heartbeat at ``t`` (default: now), on the clock's timebase."""
        self._last = self._clock.now() if t is None else t

    def __call__(self) -> HealthReport | None:
        """Latest report, or ``None`` if no heartbeat has been seen yet."""
        if self._last is None:
            return None
        fresh = (self._clock.now() - self._last) <= self._max_age_s
        return HealthReport(
            state=HealthState.OK if fresh else HealthState.NO_DATA,
            arm_permitted=fresh,
            reasons=() if fresh else ("heartbeat_stale",),
            t_mono=self._last,
        )
