"""LANDING_TARGET angle math + publish gating + send args (fake pymavlink conn)."""

from __future__ import annotations

import pytest

from jetson_yolo_gcs.core.config import MavlinkSettings
from jetson_yolo_gcs.core.errors import MavlinkError
from jetson_yolo_gcs.detection.base import Detection, DetectionResult
from jetson_yolo_gcs.mavlink.bridge import LandingTargetBridge, compute_angles
from jetson_yolo_gcs.mavlink.heartbeat import HeartbeatMonitor
from tests.conftest import FakeClock
from tests.unit.test_mavlink_heartbeat import SettableClock


class _FakeMav:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def landing_target_send(self, *args: object) -> None:
        self.calls.append(args)


class _FakeMsg:
    """Duck-typed pymavlink HEARTBEAT (only the accessors the bridge reads)."""

    def __init__(self, src_system: int = 1, src_component: int = 1) -> None:
        self._sys = src_system
        self._comp = src_component

    def get_srcSystem(self) -> int:  # noqa: N802 - pymavlink accessor name
        return self._sys

    def get_srcComponent(self) -> int:  # noqa: N802 - pymavlink accessor name
        return self._comp


class _FakeConn:
    def __init__(self, heartbeats: list[object] | None = None) -> None:
        self.mav = _FakeMav()
        self.closed = False
        #: Messages returned by successive ``recv_match`` calls, then ``None`` forever.
        self._inbox: list[object] = list(heartbeats or [])
        self.recv_calls = 0

    def recv_match(self, *, type: str, blocking: bool) -> object | None:  # noqa: A002
        self.recv_calls += 1
        assert type == "HEARTBEAT" and blocking is False
        return self._inbox.pop(0) if self._inbox else None

    def close(self) -> None:
        self.closed = True


def _fresh_monitor() -> HeartbeatMonitor:
    """A heartbeat monitor with a just-recorded, in-window beat (gate open)."""
    mon = HeartbeatMonitor(SettableClock(100.0), max_age_s=2.0)
    mon.beat(t=100.0)
    return mon


def _result_with(bbox: tuple[float, float, float, float]) -> tuple[Detection, DetectionResult]:
    det = Detection(class_id=0, class_name="pad", confidence=1.0, bbox=bbox)
    return det, DetectionResult(detections=(det,), width=200, height=200)


def test_compute_angles_centered_is_zero() -> None:
    det, result = _result_with((90, 90, 110, 110))  # centre (100,100) of 200x200
    ax, ay = compute_angles(det, result, fov_x_rad=1.0, fov_y_rad=1.0)
    assert ax == pytest.approx(0.0)
    assert ay == pytest.approx(0.0)


def test_compute_angles_right_of_centre_is_positive() -> None:
    det, result = _result_with((140, 90, 160, 110))  # centre x=150 -> +0.25 * fov
    ax, _ = compute_angles(det, result, fov_x_rad=2.0, fov_y_rad=2.0)
    assert ax == pytest.approx(0.5)


def test_publish_noop_when_disabled() -> None:
    conn = _FakeConn()
    bridge = LandingTargetBridge(MavlinkSettings(enable_landing_target=False), connection=conn)
    det, result = _result_with((90, 90, 110, 110))
    assert bridge.publish(det, result) is False
    assert conn.mav.calls == []


def test_publish_sends_landing_target_when_enabled() -> None:
    # Contract (2026-07): with the fail-closed gate on, a fresh heartbeat must back the send.
    conn = _FakeConn()
    bridge = LandingTargetBridge(
        MavlinkSettings(enable_landing_target=True, fov_x_rad=2.0, fov_y_rad=2.0),
        connection=conn,
        clock=FakeClock(times=[2.0]),
        heartbeat=_fresh_monitor(),
    )
    det, result = _result_with((140, 90, 160, 110))
    assert bridge.publish(det, result) is True
    assert len(conn.mav.calls) == 1
    args = conn.mav.calls[0]
    assert args[0] == 2_000_000  # time_usec from clock
    assert args[1] == 0  # target_num
    assert args[2] == 12  # MAV_FRAME_BODY_FRD
    assert args[3] == pytest.approx(0.5)  # angle_x


def test_publish_opens_connection_via_factory_when_none() -> None:
    conn = _FakeConn()
    bridge = LandingTargetBridge(
        MavlinkSettings(enable_landing_target=True),
        connection_factory=lambda: conn,
        heartbeat=_fresh_monitor(),
    )
    det, result = _result_with((90, 90, 110, 110))
    assert bridge.publish(det, result) is True
    assert len(conn.mav.calls) == 1


def test_publish_suppressed_when_no_heartbeat() -> None:
    # Default MavlinkSettings has require_heartbeat=True; with no beat the gate fails closed.
    conn = _FakeConn()
    bridge = LandingTargetBridge(MavlinkSettings(enable_landing_target=True), connection=conn)
    det, result = _result_with((90, 90, 110, 110))
    assert bridge.publish(det, result) is False
    assert conn.mav.calls == []


def test_publish_suppressed_when_heartbeat_stale() -> None:
    conn = _FakeConn()
    clk = SettableClock(100.0)
    mon = HeartbeatMonitor(clk, max_age_s=2.0)
    mon.beat(t=100.0)
    clk.t = 105.0  # aged past the window -> stale
    bridge = LandingTargetBridge(
        MavlinkSettings(enable_landing_target=True), connection=conn, heartbeat=mon
    )
    det, result = _result_with((90, 90, 110, 110))
    assert bridge.publish(det, result) is False
    assert conn.mav.calls == []


def test_publish_without_gate_when_require_heartbeat_false() -> None:
    conn = _FakeConn()
    bridge = LandingTargetBridge(
        MavlinkSettings(enable_landing_target=True, require_heartbeat=False),
        connection=conn,
    )
    det, result = _result_with((90, 90, 110, 110))
    assert bridge.publish(det, result) is True
    assert len(conn.mav.calls) == 1


def test_poll_heartbeat_records_target_beat_and_opens_gate() -> None:
    conn = _FakeConn(heartbeats=[_FakeMsg(src_system=1, src_component=1)])
    bridge = LandingTargetBridge(
        MavlinkSettings(enable_landing_target=True, target_system=1, target_component=1),
        connection=conn,
    )
    det, result = _result_with((90, 90, 110, 110))
    assert bridge.publish(det, result) is False  # gate closed before any beat
    assert bridge.poll_heartbeat() is True  # consumed the HEARTBEAT
    assert bridge.publish(det, result) is True  # gate now open
    assert len(conn.mav.calls) == 1


def test_poll_heartbeat_ignores_non_target_source() -> None:
    conn = _FakeConn(heartbeats=[_FakeMsg(src_system=99, src_component=1)])
    bridge = LandingTargetBridge(
        MavlinkSettings(enable_landing_target=True, target_system=1, target_component=1),
        connection=conn,
    )
    assert bridge.poll_heartbeat() is False  # wrong system id -> ignored
    det, result = _result_with((90, 90, 110, 110))
    assert bridge.publish(det, result) is False  # gate stays closed


def test_poll_heartbeat_wildcard_accepts_any_source() -> None:
    conn = _FakeConn(heartbeats=[_FakeMsg(src_system=42, src_component=7)])
    bridge = LandingTargetBridge(
        MavlinkSettings(enable_landing_target=True, target_system=0, target_component=0),
        connection=conn,
    )
    assert bridge.poll_heartbeat() is True


def test_poll_heartbeat_noop_without_connection_or_gate() -> None:
    # Factory yields nothing -> the link can't open -> nothing to read (no real IO).
    bridge = LandingTargetBridge(
        MavlinkSettings(enable_landing_target=True), connection_factory=lambda: None
    )
    assert bridge.poll_heartbeat() is False
    # Gate disabled -> poll is a no-op even with a connection (never touches the link).
    conn = _FakeConn(heartbeats=[_FakeMsg()])
    bridge2 = LandingTargetBridge(
        MavlinkSettings(enable_landing_target=True, require_heartbeat=False),
        connection=conn,
    )
    assert bridge2.poll_heartbeat() is False
    assert conn.recv_calls == 0


def test_poll_heartbeat_lazily_opens_link_via_factory() -> None:
    # Gate on, connection never explicitly started: poll must open the link (via the factory)
    # so heartbeats can be received and the gate can eventually open — not stay closed forever.
    conn = _FakeConn(heartbeats=[_FakeMsg(src_system=1, src_component=1)])
    bridge = LandingTargetBridge(
        MavlinkSettings(enable_landing_target=True, target_system=1, target_component=1),
        connection_factory=lambda: conn,
    )
    assert bridge.poll_heartbeat() is True  # lazily opened the link and consumed the beat
    det, result = _result_with((90, 90, 110, 110))
    assert bridge.publish(det, result) is True  # gate now open
    assert len(conn.mav.calls) == 1


def test_poll_heartbeat_swallows_link_open_error() -> None:
    def _boom_factory() -> object:
        raise OSError("cannot open link")

    bridge = LandingTargetBridge(
        MavlinkSettings(enable_landing_target=True), connection_factory=_boom_factory
    )
    assert bridge.poll_heartbeat() is False  # open error swallowed, loop survives


def test_poll_heartbeat_swallows_read_error() -> None:
    class _BoomConn:
        def __init__(self) -> None:
            self.mav = _FakeMav()

        def recv_match(self, *, type: str, blocking: bool) -> object:  # noqa: A002
            raise OSError("link read failed")

    bridge = LandingTargetBridge(
        MavlinkSettings(enable_landing_target=True), connection=_BoomConn()
    )
    assert bridge.poll_heartbeat() is False  # error is swallowed, not raised


def test_close_is_idempotent_and_closes_connection() -> None:
    conn = _FakeConn()
    bridge = LandingTargetBridge(MavlinkSettings(), connection=conn)
    bridge.close()
    bridge.close()
    assert conn.closed is True


def test_close_swallows_connection_close_error() -> None:
    class _BadConn:
        def __init__(self) -> None:
            self.mav = _FakeMav()

        def close(self) -> None:
            raise OSError("link already gone")

    bridge = LandingTargetBridge(MavlinkSettings(), connection=_BadConn())
    bridge.close()  # best-effort teardown must not raise


def test_close_with_non_callable_close_attr() -> None:
    class _NoCloseConn:
        mav = _FakeMav()
        close = None  # not callable

    bridge = LandingTargetBridge(MavlinkSettings(), connection=_NoCloseConn())
    bridge.close()  # no-op, must not raise


def test_publish_raises_mavlink_error_when_no_connection() -> None:
    # Gate open (fresh beat) but the factory yields no connection: publish must fail loud,
    # not silently drop — a missing link is a real fault, distinct from a heartbeat miss.
    bridge = LandingTargetBridge(
        MavlinkSettings(enable_landing_target=True),
        connection_factory=lambda: None,
        heartbeat=_fresh_monitor(),
    )
    det, result = _result_with((90, 90, 110, 110))
    with pytest.raises(MavlinkError):
        bridge.publish(det, result)


def test_suppressed_publish_logs_are_rate_limited() -> None:
    # The gate stays closed; repeated suppressed publishes must not raise and the bridge
    # tracks the running suppression count (used to throttle the warning).
    conn = _FakeConn()
    bridge = LandingTargetBridge(MavlinkSettings(enable_landing_target=True), connection=conn)
    det, result = _result_with((90, 90, 110, 110))
    for _ in range(5):
        assert bridge.publish(det, result) is False
    assert conn.mav.calls == []
