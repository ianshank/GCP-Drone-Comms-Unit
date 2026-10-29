"""Suppression accounting for the ``LANDING_TARGET`` bridge (code-hygiene-modularity T-4.5).

Extracted from :class:`~jetson_yolo_gcs.mavlink.bridge.LandingTargetBridge`: the per-reason
monotonic counters (observability), the shared throttle streak (resets on a successful
send) and the "1st + every Nth" warning cadence are one small, independently testable
object instead of three attributes and a method on the bridge.
"""

from __future__ import annotations

from typing import Any

import structlog

from ..utils.log_throttle import should_log_throttled

_log = structlog.get_logger("jetson_yolo_gcs.mavlink.bridge")


class SuppressionCounter:
    """Count suppressed publishes by reason and warn on a throttled cadence.

    ``reasons`` are cumulative and never reset (``"no_heartbeat"``/``"no_pose"``/
    ``"unprojectable"`` today); ``streak`` counts suppressions since the last successful
    send and drives the "1st + every ``log_every``th" warning so a silent link is visible
    without flooding the log at frame rate.
    """

    def __init__(self, log_every: int, *, log: Any = _log) -> None:
        if log_every < 1:
            raise ValueError(f"log_every must be >= 1, got {log_every}")
        self._log_every = log_every
        self._log = log
        self._by_reason: dict[str, int] = {}
        self._streak = 0

    @property
    def streak(self) -> int:
        """Suppressions since the last :meth:`reset` (the throttle streak)."""
        return self._streak

    def note(self, reason: str, message: str, **fields: object) -> None:
        """Account one suppression by ``reason`` and emit the throttled warning."""
        self._by_reason[reason] = self._by_reason.get(reason, 0) + 1
        self._streak += 1
        if should_log_throttled(self._streak, self._log_every):
            self._log.warning(message, suppressed=self._streak, reason=reason, **fields)

    def reset(self) -> None:
        """A successful send: the throttle streak starts over (reasons stay cumulative)."""
        self._streak = 0

    def snapshot(self) -> dict[str, int]:
        """Cumulative suppression counts keyed by reason (a copy — safe to expose)."""
        return dict(self._by_reason)
