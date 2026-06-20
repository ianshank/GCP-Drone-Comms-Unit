"""LANDING_TARGET angle math + publish gating + send args (fake pymavlink conn)."""

from __future__ import annotations

import pytest

from jetson_yolo_gcs.core.config import MavlinkSettings
from jetson_yolo_gcs.detection.base import Detection, DetectionResult
from jetson_yolo_gcs.mavlink.bridge import LandingTargetBridge, compute_angles
from tests.conftest import FakeClock


class _FakeMav:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def landing_target_send(self, *args: object) -> None:
        self.calls.append(args)


class _FakeConn:
    def __init__(self) -> None:
        self.mav = _FakeMav()
        self.closed = False

    def close(self) -> None:
        self.closed = True


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
    bridge.publish(det, result)
    assert conn.mav.calls == []


def test_publish_sends_landing_target_when_enabled() -> None:
    conn = _FakeConn()
    bridge = LandingTargetBridge(
        MavlinkSettings(enable_landing_target=True, fov_x_rad=2.0, fov_y_rad=2.0),
        connection=conn,
        clock=FakeClock(times=[2.0]),
    )
    det, result = _result_with((140, 90, 160, 110))
    bridge.publish(det, result)
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
    )
    det, result = _result_with((90, 90, 110, 110))
    bridge.publish(det, result)
    assert len(conn.mav.calls) == 1


def test_close_is_idempotent_and_closes_connection() -> None:
    conn = _FakeConn()
    bridge = LandingTargetBridge(MavlinkSettings(), connection=conn)
    bridge.close()
    bridge.close()
    assert conn.closed is True
