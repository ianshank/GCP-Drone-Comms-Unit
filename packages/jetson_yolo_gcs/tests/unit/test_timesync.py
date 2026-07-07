"""Vehicle-clock offset holder for LANDING_TARGET.time_usec (Task 14)."""

from __future__ import annotations

from jetson_yolo_gcs.mavlink.timesync import TimeSync


def test_timesync_applies_offset() -> None:
    ts = TimeSync(offset_us=1_000_000)  # vehicle clock 1s ahead
    assert ts.to_vehicle_usec(2.0) == 3_000_000


def test_timesync_default_offset_is_zero() -> None:
    ts = TimeSync()
    assert ts.offset_us == 0
    assert ts.to_vehicle_usec(2.0) == 2_000_000


def test_timesync_negative_offset_is_subtracted() -> None:
    ts = TimeSync(offset_us=-500_000)  # vehicle clock 0.5s behind
    assert ts.to_vehicle_usec(2.0) == 1_500_000
