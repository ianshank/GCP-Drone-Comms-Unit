"""Unit tests for the ``LANDING_TARGET`` frame encoders and the suppression counter (T-4.5)."""

from __future__ import annotations

import pytest
import structlog

from jetson_yolo_gcs.detection.base import Detection, DetectionResult
from jetson_yolo_gcs.geometry.ned import NedOffset
from jetson_yolo_gcs.mavlink.frames import (
    IDENTITY_QUATERNION_WXYZ,
    LANDING_TARGET_TYPE_LIGHT_BEACON,
    MAV_FRAME_BODY_FRD,
    MAV_FRAME_LOCAL_NED,
    compute_angles,
    encode_body_frd,
    encode_local_ned,
)
from jetson_yolo_gcs.mavlink.suppression import SuppressionCounter


def _result(width: int = 100, height: int = 50) -> tuple[Detection, DetectionResult]:
    det = Detection(class_id=0, class_name="pad", confidence=0.9, bbox=(60.0, 10.0, 80.0, 20.0))
    return det, DetectionResult(detections=(det,), width=width, height=height)


def test_body_frd_frame_layout_is_pinned() -> None:
    det, result = _result()
    frame = encode_body_frd(det, result, fov_x_rad=1.0, fov_y_rad=2.0, time_usec=123)
    # Angles pinned as literals, not via compute_angles(): bbox centre (70, 15) in a
    # 100x50 image is +0.2 of the width right of centre and 0.2 of the height *above*
    # centre, so angle_x = +0.2 * fov_x and angle_y = -0.2 * fov_y (image y grows down).
    assert frame[:3] == (123, 0, MAV_FRAME_BODY_FRD)
    assert frame[3:5] == pytest.approx((0.2, -0.4))
    assert frame[5:] == (
        0.0,
        (20.0 / 100) * 1.0,  # size_x = bbox width / image width * fov_x
        (10.0 / 50) * 2.0,  # size_y = bbox height / image height * fov_y
    )
    assert frame[3:5] == compute_angles(det, result, fov_x_rad=1.0, fov_y_rad=2.0)
    assert all(isinstance(v, float) for v in frame[3:])


def test_body_frd_frame_degrades_to_zero_sizes_on_an_empty_image() -> None:
    det, result = _result(width=0, height=0)
    frame = encode_body_frd(det, result, fov_x_rad=1.0, fov_y_rad=1.0, time_usec=1)
    assert frame[3:] == (0.0, 0.0, 0.0, 0.0, 0.0)


def test_local_ned_frame_layout_is_pinned() -> None:
    frame = encode_local_ned(NedOffset(north_m=1.5, east_m=-2.0, down_m=3.25), time_usec=7)
    assert frame == (
        7,
        0,
        MAV_FRAME_LOCAL_NED,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        1.5,
        -2.0,
        3.25,
        IDENTITY_QUATERNION_WXYZ,
        LANDING_TARGET_TYPE_LIGHT_BEACON,
        1,
    )
    assert len(frame) == 14  # the full pymavlink landing_target_send positional list
    assert IDENTITY_QUATERNION_WXYZ == (1.0, 0.0, 0.0, 0.0)


def test_suppression_counter_counts_by_reason_and_throttles() -> None:
    counter = SuppressionCounter(3)
    with structlog.testing.capture_logs() as cap:
        for _ in range(4):
            counter.note("no_heartbeat", "suppressed", reasons=("stale",))
        counter.note("no_pose", "suppressed")
    assert counter.snapshot() == {"no_heartbeat": 4, "no_pose": 1}
    assert counter.streak == 5
    # 1st + every 3rd of the shared streak: suppressions 1, 3 (both heartbeat).
    assert [(e["suppressed"], e["reason"]) for e in cap] == [
        (1, "no_heartbeat"),
        (3, "no_heartbeat"),
    ]
    assert cap[0]["reasons"] == ("stale",)


def test_suppression_counter_reset_restarts_the_streak_but_keeps_reasons() -> None:
    counter = SuppressionCounter(2)
    counter.note("no_pose", "m")
    counter.note("no_pose", "m")
    counter.reset()
    assert counter.streak == 0
    assert counter.snapshot() == {"no_pose": 2}
    snapshot = counter.snapshot()
    snapshot["no_pose"] = 99  # a copy, not the live dict
    assert counter.snapshot() == {"no_pose": 2}


def test_suppression_counter_rejects_a_zero_cadence() -> None:
    import pytest

    with pytest.raises(ValueError, match="log_every must be >= 1, got 0"):
        SuppressionCounter(0)
