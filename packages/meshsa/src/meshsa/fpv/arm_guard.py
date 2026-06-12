"""Pre-flight arm-gating enforcement wrapper (§5.6, §4.1).

``ArmGuard`` wraps any :class:`meshsa.fpv.protocols.RCLink` and itself satisfies
``RCLink`` (decorator pattern), so interposing it is transparent to callers.

Authority is deliberately minimal and **structurally incapable of in-flight
intervention**:

* It gates only the **disarmed -> armed** transition. While disarmed, an arm
  command (arm channel >= ``arm_threshold_us``) is allowed only if the most
  recent :class:`HealthReport` is fresher than ``arm_guard_report_max_age_s`` and
  ``arm_permitted`` is True; otherwise the arm channel is clamped to
  ``arm_clamp_us`` (kept low), the rest of the frame passes through, and an
  ``arm_blocked`` event is emitted.
* **Latch — never disarms.** Once an armed frame passes, the guard latches and
  applies no further clamping until it observes the caller command the arm
  channel low (operator disarm/E-stop). Degraded health in flight therefore
  produces advisory alerts elsewhere, never intervention here — §4.1 made
  mechanical.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

import structlog

from ..protocols import Clock
from .config import ArmGuardSettings
from .errors import ArmGuardError
from .link_health import HealthReport
from .protocols import RCLink

_log = structlog.get_logger("meshsa.fpv.armguard")

#: Optional event callback ``(event_name, data)`` — wire to ``FlightLogger.record_event``.
EventSink = Callable[[str, dict[str, Any]], None]


class ArmGuard:
    """An ``RCLink`` decorator that enforces health-gated pre-flight arming."""

    def __init__(
        self,
        link: RCLink,
        settings: ArmGuardSettings,
        clock: Clock,
        *,
        on_event: EventSink | None = None,
    ) -> None:
        self._link = link
        self._s = settings
        self._clock = clock
        self._on_event = on_event
        self._latched = False
        self._last_report: HealthReport | None = None

    def update_health(self, report: HealthReport) -> None:
        """Feed the latest health report used to authorize arming."""
        self._last_report = report

    @property
    def latched(self) -> bool:
        """True once an armed frame has passed (until the operator disarms)."""
        return self._latched

    def send_rc(self, channels: Sequence[int]) -> None:
        """Forward an RC frame, clamping the arm channel low if arming is blocked."""
        idx = self._s.arm_channel_index
        if len(channels) <= idx:
            raise ArmGuardError(f"channels length {len(channels)} <= arm_channel_index {idx}")
        chans = list(channels)
        wants_arm = chans[idx] >= self._s.arm_threshold_us

        if self._latched:
            # In flight: never clamp. Only an operator-commanded low releases it.
            if not wants_arm:
                self._latched = False
                _log.debug("arm latch released by operator disarm")
            self._link.send_rc(chans)
            return

        if not wants_arm:
            # Disarmed and not arming -> pass through untouched.
            self._link.send_rc(chans)
            return

        # Disarmed -> arming transition: gate on fresh-OK health.
        if self._arm_allowed():
            self._latched = True
            _log.debug("arm permitted; latching", arm_us=chans[idx])
            self._link.send_rc(chans)
        else:
            attempted = chans[idx]
            chans[idx] = self._s.arm_clamp_us
            self._emit_blocked(attempted)
            self._link.send_rc(chans)

    def _arm_allowed(self) -> bool:
        report = self._last_report
        if report is None:
            return False
        age = self._clock.now() - report.t_mono
        return age <= self._s.arm_guard_report_max_age_s and report.arm_permitted

    def _emit_blocked(self, attempted_us: int) -> None:
        report = self._last_report
        data = {
            "attempted_us": attempted_us,
            "clamped_to_us": self._s.arm_clamp_us,
            "health_state": report.state.value if report is not None else None,
            "report_reasons": list(report.reasons) if report is not None else [],
        }
        _log.info("arm blocked", **data)
        if self._on_event is not None:
            self._on_event("arm_blocked", data)
