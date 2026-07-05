"""Tests for meshsa.scout.sync.TimeSync — nearest match + max-skew drop-and-count."""

from __future__ import annotations

from meshsa.cv.geo import Pose
from meshsa.scout.pose import FusedPose
from meshsa.scout.sync import TimeSync


def _fp(ts: float) -> FusedPose:
    return FusedPose(
        pose=Pose(lat=0.0, lon=0.0, alt_agl_m=60.0, heading_deg=0.0, pitch_deg=90.0),
        roll_deg=0.0,
        ts=ts,
    )


def test_align_returns_nearest() -> None:
    sync = TimeSync(max_skew_s=0.5)
    sync.add_pose(_fp(1.0))
    sync.add_pose(_fp(2.0))
    match = sync.align(1.9)
    assert match is not None
    assert match.ts == 2.0
    assert sync.dropped == 0


def test_align_drops_when_skew_exceeded() -> None:
    sync = TimeSync(max_skew_s=0.1)
    sync.add_pose(_fp(1.0))
    assert sync.align(5.0) is None
    assert sync.dropped == 1


def test_align_empty_buffer_drops() -> None:
    sync = TimeSync(max_skew_s=1.0)
    assert sync.align(1.0) is None
    assert sync.dropped == 1


def test_align_handles_out_of_order_inserts() -> None:
    # The lazy sort must give the correct nearest even when poses arrive out of ts order.
    sync = TimeSync(max_skew_s=0.5)
    for t in (3.0, 1.0, 2.0):
        sync.add_pose(_fp(t))
    assert sync.align(1.1).ts == 1.0  # type: ignore[union-attr]
    assert sync.align(2.9).ts == 3.0  # type: ignore[union-attr]


def test_add_pose_invalidates_sorted_index() -> None:
    sync = TimeSync(max_skew_s=0.5)
    sync.add_pose(_fp(1.0))
    assert sync.align(1.0) is not None  # builds the sorted index
    sync.add_pose(_fp(5.0))  # must invalidate so the new pose is findable
    assert sync.align(5.0).ts == 5.0  # type: ignore[union-attr]


def test_buffer_is_bounded() -> None:
    sync = TimeSync(max_skew_s=100.0, buffer_size=2)
    for t in (1.0, 2.0, 3.0):
        sync.add_pose(_fp(t))
    # Oldest (1.0) evicted; nearest to 1.0 is now 2.0.
    match = sync.align(1.0)
    assert match is not None
    assert match.ts == 2.0
