"""Heartbeat-driven pre-arm health provider (fakes-only)."""

from conftest import SettableClock

from meshsa.command import HeartbeatHealth
from meshsa.fpv.link_health import HealthState


def test_no_heartbeat_yet_is_none():
    assert HeartbeatHealth(SettableClock(100.0))() is None


def test_fresh_heartbeat_permits_arming():
    clk = SettableClock(100.0)
    h = HeartbeatHealth(clk, max_age_s=3.0)
    h.beat()  # at t=100
    clk.t = 102.0  # 2s later -> still fresh
    report = h()
    assert report is not None
    assert report.arm_permitted is True
    assert report.state is HealthState.OK
    assert report.t_mono == 100.0


def test_stale_heartbeat_blocks_arming():
    clk = SettableClock(100.0)
    h = HeartbeatHealth(clk, max_age_s=3.0)
    h.beat()  # at t=100
    clk.t = 105.0  # 5s later -> stale
    report = h()
    assert report is not None
    assert report.arm_permitted is False
    assert report.state is HealthState.NO_DATA
    assert report.reasons == ("heartbeat_stale",)


def test_explicit_timestamp_is_used():
    clk = SettableClock(200.0)
    h = HeartbeatHealth(clk)
    h.beat(t=50.0)
    assert h()  # truthy report exists
    assert h().t_mono == 50.0
