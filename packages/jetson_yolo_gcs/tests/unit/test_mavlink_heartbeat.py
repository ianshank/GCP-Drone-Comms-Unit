"""Fail-closed autopilot-heartbeat freshness gate (deterministic clock)."""

from __future__ import annotations

from jetson_yolo_gcs.mavlink.heartbeat import HeartbeatMonitor


class SettableClock:
    """Controllable, non-advancing clock so freshness ages are asserted exactly."""

    def __init__(self, t: float = 100.0) -> None:
        self.t = t

    def now(self) -> float:
        return self.t


def test_no_heartbeat_yet_is_not_fresh() -> None:
    mon = HeartbeatMonitor(SettableClock(100.0), max_age_s=2.0)
    report = mon.report()
    assert report.fresh is False
    assert report.reasons == ("no_heartbeat",)
    assert report.last_beat_t is None
    assert mon.is_fresh() is False


def test_fresh_within_window() -> None:
    clk = SettableClock(100.0)
    mon = HeartbeatMonitor(clk, max_age_s=2.0)
    mon.beat()  # recorded at t=100
    clk.t = 102.0  # 2 s later -> still within the 2 s window
    report = mon.report()
    assert report.fresh is True
    assert report.reasons == ()
    assert report.last_beat_t == 100.0
    assert mon.is_fresh() is True


def test_stale_beyond_window() -> None:
    clk = SettableClock(100.0)
    mon = HeartbeatMonitor(clk, max_age_s=2.0)
    mon.beat()  # at t=100
    clk.t = 103.0  # 3 s later -> stale
    report = mon.report()
    assert report.fresh is False
    assert report.reasons == ("heartbeat_stale",)
    assert report.last_beat_t == 100.0
    assert mon.is_fresh() is False


def test_explicit_beat_timestamp_is_used() -> None:
    clk = SettableClock(100.0)
    mon = HeartbeatMonitor(clk, max_age_s=5.0)
    mon.beat(t=98.0)  # explicit timestamp overrides the clock reading
    assert mon.report().last_beat_t == 98.0
    assert mon.is_fresh() is True  # 100 - 98 = 2 <= 5


def test_report_accepts_explicit_now() -> None:
    mon = HeartbeatMonitor(SettableClock(100.0), max_age_s=2.0)
    mon.beat(t=100.0)
    assert mon.report(now=101.0).fresh is True
    assert mon.report(now=103.0).fresh is False


def test_defaults_to_monotonic_clock() -> None:
    # No clock injected: is_fresh must be callable and fail-closed before any beat.
    mon = HeartbeatMonitor(max_age_s=1.0)
    assert mon.is_fresh() is False


def test_subsequent_beats_refresh_without_reacquire_log() -> None:
    # A second beat exercises the "already acquired" branch (no first-acquisition log) and
    # advances the freshness anchor.
    clk = SettableClock(100.0)
    mon = HeartbeatMonitor(clk, max_age_s=2.0)
    mon.beat(t=100.0)
    mon.beat(t=105.0)  # refresh
    assert mon.report().last_beat_t == 105.0
    assert mon.report(now=106.0).fresh is True
