"""LinkHealthMonitor: co-signal model, hysteresis, transitions (§4.2, §5.3)."""

from __future__ import annotations

from meshsa.fpv.config import HealthSettings
from meshsa.fpv.crsf.telemetry import LinkStatistics
from meshsa.fpv.link_health import (
    ConsoleAlertSink,
    HealthReport,
    HealthState,
    LinkHealthMonitor,
)
from meshsa.fpv.telemetry_store import TelemetryStore


class ManualClock:
    """A clock whose time only advances when told (precise hysteresis tests)."""

    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def now(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


class RecordingSink:
    def __init__(self) -> None:
        self.events: list[tuple[HealthState, HealthState | None]] = []

    def alert(self, report: HealthReport, previous: HealthReport | None) -> None:
        self.events.append((report.state, previous.state if previous else None))


def _ls(
    *, uplink_lq: int = 100, downlink_lq: int = 100, rssi: int = -50, rf_mode: int = 0
) -> LinkStatistics:
    return LinkStatistics(
        uplink_rssi_ant1_dbm=rssi,
        uplink_rssi_ant2_dbm=rssi,
        uplink_lq=uplink_lq,
        uplink_snr_db=8,
        active_antenna=0,
        rf_mode=rf_mode,
        uplink_tx_power_mw=100,
        downlink_rssi_dbm=-50,
        downlink_lq=downlink_lq,
        downlink_snr_db=8,
    )


def _make(settings: HealthSettings | None = None, sink=None):
    store = TelemetryStore()
    clock = ManualClock()
    mon = LinkHealthMonitor(settings or HealthSettings(), store, clock, sink)
    return mon, store, clock


def _drive_to_ok(mon, store, clock, **ls_kwargs) -> HealthReport:
    """Push fresh good telemetry and advance past hysteresis to reach OK."""
    store.update(_ls(**ls_kwargs), clock.now())
    r = mon.evaluate()  # NO_DATA -> pending OK
    assert r.state is HealthState.NO_DATA
    clock.advance(HealthSettings().health_hysteresis_s)
    store.update(_ls(**ls_kwargs), clock.now())
    return mon.evaluate()


def test_no_data_when_store_empty():
    mon, _store, _clock = _make()
    r = mon.evaluate()
    assert r.state is HealthState.NO_DATA
    assert r.arm_permitted is False
    assert r.reasons == ("no_telemetry",)


def test_acquisition_to_ok_requires_hysteresis():
    mon, store, clock = _make()
    r = _drive_to_ok(mon, store, clock)
    assert r.state is HealthState.OK
    assert r.arm_permitted is True
    assert r.reasons == ()


def test_degradation_is_immediate():
    mon, store, clock = _make()
    _drive_to_ok(mon, store, clock)
    # A critically low LQ frame degrades immediately (no hysteresis).
    store.update(_ls(uplink_lq=10), clock.now())
    r = mon.evaluate()
    assert r.state is HealthState.CRITICAL
    assert r.reasons == ("lq_below_critical",)
    assert r.arm_permitted is False


def test_lq_below_warn_is_warn():
    mon, store, clock = _make()
    _drive_to_ok(mon, store, clock)
    store.update(_ls(uplink_lq=60), clock.now())  # 50 <= 60 < 70
    r = mon.evaluate()
    assert r.state is HealthState.WARN
    assert r.reasons == ("lq_below_warn",)


def test_stale_linkstats_can_never_be_ok():
    mon, store, clock = _make()
    _drive_to_ok(mon, store, clock)
    s = HealthSettings()
    # Age beyond stale -> WARN even though the stored frame was perfect.
    clock.advance(s.health_linkstats_stale_s + 0.01)
    r = mon.evaluate()
    assert r.state is HealthState.WARN
    assert r.reasons == ("linkstats_stale",)
    # Beyond 2x -> CRITICAL.
    clock.advance(s.health_linkstats_stale_s)
    r = mon.evaluate()
    assert r.state is HealthState.CRITICAL
    assert r.reasons == ("linkstats_stale",)
    assert r.arm_permitted is False


def test_downlink_degrading_early_warning_while_uplink_clean():
    mon, store, clock = _make()
    _drive_to_ok(mon, store, clock)
    # Uplink LQ perfect, but downlink LQ trending below the early-warning floor.
    store.update(_ls(uplink_lq=100, downlink_lq=40), clock.now())
    r = mon.evaluate()
    assert r.state is HealthState.WARN
    assert "downlink_degrading" in r.reasons


def test_version_keyed_floor_selection_changes_outcome():
    # rf_mode=2, rssi=-105. ELRS 3 floor=-112, +10 margin => threshold -102:
    # -105 < -102 -> rssi_below_margin WARN.
    s3 = HealthSettings(elrs_major_version=3)
    mon, store, clock = _make(s3)
    _drive_to_ok(mon, store, clock, rf_mode=2, rssi=-105, uplink_lq=100, downlink_lq=100)
    store.update(_ls(rf_mode=2, rssi=-105), clock.now())
    r = mon.evaluate()
    assert r.state is HealthState.WARN
    assert "rssi_below_margin" in r.reasons

    # Same signal, ELRS major 2 has NO floor map entry -> no rssi escalation -> OK.
    s2 = HealthSettings(elrs_major_version=2)
    mon2, store2, clock2 = _make(s2)
    r2 = _drive_to_ok(mon2, store2, clock2, rf_mode=2, rssi=-105)
    assert r2.state is HealthState.OK
    assert "rssi_below_margin" not in r2.reasons


def test_rssi_uses_active_antenna_for_diversity():
    # ELRS 3, rf_mode 2 -> floor -112; +10 margin => threshold -102. The RSSI
    # co-signal must judge the *active* antenna, not always antenna 1.
    s = HealthSettings(elrs_major_version=3)

    def reasons_for(ant1: int, ant2: int, active: int) -> tuple[str, ...]:
        mon, store, clock = _make(s)
        # Reach confirmed OK first (rf_mode 2, strong RSSI) so the next frame's
        # reasons reflect the raw evaluation rather than a hysteresis hold.
        _drive_to_ok(mon, store, clock, rf_mode=2, rssi=-50)
        store.update(LinkStatistics(ant1, ant2, 100, 8, active, 2, 100, -50, 100, 8), clock.now())
        return mon.evaluate().reasons

    # Active antenna = ant2: a strong ant2 keeps the link clean even if ant1 is weak.
    assert "rssi_below_margin" not in reasons_for(-105, -50, active=1)
    # Active antenna = ant2: a weak ant2 warns, ignoring a strong (idle) ant1.
    assert "rssi_below_margin" in reasons_for(-50, -105, active=1)
    # Active antenna = ant1: a weak ant1 warns.
    assert "rssi_below_margin" in reasons_for(-105, -50, active=0)


def test_recovery_is_hysteresis_damped():
    mon, store, clock = _make()
    _drive_to_ok(mon, store, clock)
    # Degrade to WARN immediately.
    store.update(_ls(uplink_lq=60), clock.now())
    assert mon.evaluate().state is HealthState.WARN
    # Good frame again, but recovery must persist for the hysteresis window. The
    # held WARN must carry an explicit reason rather than the (now-empty) raw OK
    # reasons, so a held state is never reasonless.
    store.update(_ls(uplink_lq=100), clock.now())
    held = mon.evaluate()
    assert held.state is HealthState.WARN  # pending OK just registered
    assert held.reasons == ("hysteresis_hold",)
    # Partial wait (< hysteresis): pending unchanged, still not upgraded.
    clock.advance(HealthSettings().health_hysteresis_s / 2)
    store.update(_ls(uplink_lq=100), clock.now())
    assert mon.evaluate().state is HealthState.WARN  # pending OK, time insufficient
    # Remaining wait crosses the window -> upgrade to OK (reasons now reflect OK).
    clock.advance(HealthSettings().health_hysteresis_s)
    store.update(_ls(uplink_lq=100), clock.now())
    recovered = mon.evaluate()
    assert recovered.state is HealthState.OK
    assert recovered.reasons == ()


def test_sink_receives_only_transitions():
    sink = RecordingSink()
    mon, store, clock = _make(sink=sink)
    mon.evaluate()  # NO_DATA (initial transition from None)
    mon.evaluate()  # still NO_DATA -> no event
    _drive_to_ok(mon, store, clock)  # -> OK
    states = [s for s, _ in sink.events]
    assert states == [HealthState.NO_DATA, HealthState.OK]
    # previous of the OK transition is NO_DATA.
    assert sink.events[-1] == (HealthState.OK, HealthState.NO_DATA)


def test_console_sink_is_non_blocking_and_safe():
    # ConsoleAlertSink only logs; it must accept a None previous without error.
    sink = ConsoleAlertSink()
    report = HealthReport(HealthState.OK, True, (), 1.0)
    sink.alert(report, None)
    sink.alert(report, report)
