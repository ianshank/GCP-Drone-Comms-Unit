"""Link-health monitor with a deliberately limited authority model (§4, §5.3).

The monitor never commands the aircraft. Its two powers are **arm gating**
(``arm_permitted`` is True only in :data:`HealthState.OK`, enforced by
:class:`meshsa.fpv.arm_guard.ArmGuard`) and **advisory alerts**. Degradation is
immediate; recovery is hysteresis-damped so the health state cannot flap an
operator. A stale LinkStatistics frame can never report OK (§4.2): freshness
degrades exactly when the link does, so trusting last-known LQ is most wrong at
the worst moment.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

import structlog

from ..protocols import Clock
from .config import HealthSettings
from .crsf.telemetry import LinkStatistics
from .protocols import AlertSink
from .telemetry_store import TelemetryStore

_log = structlog.get_logger("meshsa.fpv.health")


class HealthState(Enum):
    """Link-health states. Severity order is defined by :data:`_SEVERITY`."""

    NO_DATA = "no_data"
    OK = "ok"
    WARN = "warn"
    CRITICAL = "critical"


#: Severity ranking for hysteresis. NO_DATA ranks worst so first telemetry
#: acquisition after boot is hysteresis-damped (no arming on a single frame).
_SEVERITY: dict[HealthState, int] = {
    HealthState.OK: 0,
    HealthState.WARN: 1,
    HealthState.CRITICAL: 2,
    HealthState.NO_DATA: 3,
}


def worst_state(states: Iterable[HealthState]) -> HealthState:
    """Return the most severe of ``states`` (by :data:`_SEVERITY`), NO_DATA if empty.

    Ranking by severity — not by the string value — matters: ``"warn"`` sorts
    above ``"critical"`` lexicographically, so a naive ``max(state.value)`` would
    mis-report a run containing CRITICAL as merely WARN.
    """
    return max(states, key=lambda s: _SEVERITY[s], default=HealthState.NO_DATA)


@dataclass(frozen=True)
class HealthReport:
    """Immutable health evaluation result."""

    state: HealthState
    arm_permitted: bool
    reasons: tuple[str, ...]
    t_mono: float


class ConsoleAlertSink:
    """Non-blocking :class:`meshsa.fpv.protocols.AlertSink` that logs transitions.

    Logging only — never blocks the caller. Durable persistence of transitions is
    the flight logger's ``record_event`` responsibility, not the sink's.
    """

    def alert(self, report: HealthReport, previous: HealthReport | None) -> None:
        prev = previous.state.value if previous is not None else None
        _log.info(
            "link health transition",
            state=report.state.value,
            previous=prev,
            arm_permitted=report.arm_permitted,
            reasons=list(report.reasons),
        )


class LinkHealthMonitor:
    """Evaluates link health from the store; emits an event on every transition.

    ``evaluate`` is pure given the store and clock (the only mutable state is the
    confirmed-state/hysteresis bookkeeping it owns). Its owner — in Phase 1 the
    ``fpv-telemetry-monitor`` tool — calls it at >= 2 Hz.
    """

    def __init__(
        self,
        settings: HealthSettings,
        store: TelemetryStore,
        clock: Clock,
        sink: AlertSink | None = None,
    ) -> None:
        self._s = settings
        self._store = store
        self._clock = clock
        self._sink = sink
        self._state = HealthState.NO_DATA
        self._last_report: HealthReport | None = None
        #: Recovery candidate and when it was first observed (hysteresis).
        self._pending: HealthState | None = None
        self._pending_since = 0.0

    def evaluate(self) -> HealthReport:
        """Compute the current :class:`HealthReport`, applying hysteresis."""
        now = self._clock.now()
        raw_state, reasons = self._raw_state(now)
        confirmed = self._apply_hysteresis(raw_state, now)
        if confirmed is not raw_state:
            # Hysteresis is holding a more-severe confirmed state while the raw
            # link recovers (degradation is immediate, so this is always a
            # recovery hold). The raw reasons describe the *better* raw state, so
            # report an explicit debounce reason instead — a held WARN/CRITICAL
            # is never left reasonless.
            reasons = ("hysteresis_hold",)
        report = HealthReport(
            state=confirmed,
            arm_permitted=confirmed is HealthState.OK,
            reasons=reasons,
            t_mono=now,
        )
        previous = self._last_report
        if previous is None or previous.state is not confirmed:
            self._emit(report, previous)
        self._last_report = report
        return report

    def _raw_state(self, now: float) -> tuple[HealthState, tuple[str, ...]]:
        """Instantaneous state from the store (pre-hysteresis), with reasons."""
        entry = self._store.latest(LinkStatistics)
        if entry is None:
            return HealthState.NO_DATA, ("no_telemetry",)
        msg, t_mono = entry
        age = now - t_mono
        reasons: list[str] = []

        stale = self._s.health_linkstats_stale_s
        if age > self._s.health_linkstats_critical_factor * stale:
            return HealthState.CRITICAL, ("linkstats_stale",)
        if age > stale:
            return HealthState.WARN, ("linkstats_stale",)

        # Fresh frame: LQ thresholds apply (§4.2 rule 2).
        state = HealthState.OK
        if msg.uplink_lq < self._s.health_lq_critical:
            return HealthState.CRITICAL, ("lq_below_critical",)
        if msg.uplink_lq < self._s.health_lq_warn:
            state = HealthState.WARN
            reasons.append("lq_below_warn")

        # Downlink-LQ early-warning co-signal (§4.2 rule 3): never downgrades.
        if msg.downlink_lq < self._s.health_downlink_lq_warn:
            reasons.append("downlink_degrading")
            state = self._escalate(state, HealthState.WARN)

        # RSSI-vs-sensitivity-floor co-signal, version-keyed (§4.3). On diversity
        # receivers (common in ELRS) judge the link by the *active* antenna
        # (active_antenna: 0 = ant1, 1 = ant2) so a shadowed idle antenna never
        # raises a false degradation warning.
        floor = self._s.sensitivity_floor(self._s.elrs_major_version, msg.rf_mode)
        if floor is not None:
            active_rssi = (
                msg.uplink_rssi_ant2_dbm if msg.active_antenna == 1 else msg.uplink_rssi_ant1_dbm
            )
            if active_rssi < floor + self._s.health_rssi_margin_db:
                reasons.append("rssi_below_margin")
                state = self._escalate(state, HealthState.WARN)

        return state, tuple(reasons)

    @staticmethod
    def _escalate(current: HealthState, at_least: HealthState) -> HealthState:
        """Return whichever of ``current``/``at_least`` is more severe."""
        return at_least if _SEVERITY[at_least] > _SEVERITY[current] else current

    def _apply_hysteresis(self, raw: HealthState, now: float) -> HealthState:
        """Degradation is immediate; recovery must persist for the hysteresis window."""
        if raw is self._state:
            self._pending = None
            return self._state
        if _SEVERITY[raw] > _SEVERITY[self._state]:
            # Worse than confirmed -> apply immediately.
            self._state = raw
            self._pending = None
            return self._state
        # Better than confirmed -> require the improvement to persist.
        if self._pending is not raw:
            self._pending = raw
            self._pending_since = now
        elif now - self._pending_since >= self._s.health_hysteresis_s:
            self._state = raw
            self._pending = None
        return self._state

    def _emit(self, report: HealthReport, previous: HealthReport | None) -> None:
        prev_state = previous.state.value if previous is not None else None
        _log.debug(
            "health state change",
            from_state=prev_state,
            to_state=report.state.value,
            reasons=list(report.reasons),
        )
        if self._sink is not None:
            self._sink.alert(report, previous)
