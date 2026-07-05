"""Tests for meshsa.scout.replay — synthetic flight + async sources."""

from __future__ import annotations

from meshsa.scout.cli import sample_block
from meshsa.scout.replay import (
    DEFAULT_CAMERA,
    GroundTruth,
    ReplayDetectionSource,
    ReplayFlight,
    ReplayPoseSource,
    _truth_to_pixel,
)


def test_flight_builds_poses_and_detections() -> None:
    flight = ReplayFlight(sample_block(), rtk_enabled=True, seed=1)
    assert len(flight.poses) > 0
    assert len(flight.detections) > 0
    assert len(flight.ground_truths) == 3
    # Detections carry a valid confidence and reference a frame.
    assert all(0.0 <= d.conf <= 1.0 for d in flight.detections)
    assert all(d.frame_id for d in flight.detections)


def test_custom_truths_respected() -> None:
    truths = [GroundTruth(lat=38.5008, lon=-122.4990, cls="standing_water")]
    flight = ReplayFlight(sample_block(), truths=truths, seed=0)
    assert flight.ground_truths == truths
    assert any(d.cls == "standing_water" for d in flight.detections)


def test_truth_behind_camera_not_seen() -> None:
    from meshsa.cv.geo import Pose, destination

    pose = Pose(lat=38.5, lon=-122.5, alt_agl_m=60.0, heading_deg=90.0, pitch_deg=90.0)
    # A truth directly behind (west) the east-facing camera must not project into frame.
    behind_lat, behind_lon = destination(38.5, -122.5, 270.0, 15.0)
    assert _truth_to_pixel(pose, DEFAULT_CAMERA, behind_lat, behind_lon) is None


async def test_async_sources_yield_all() -> None:
    flight = ReplayFlight(sample_block(), seed=2)
    poses = [p async for p in ReplayPoseSource(flight).stream()]
    dets = [d async for d in ReplayDetectionSource(flight).stream()]
    assert len(poses) == len(flight.poses)
    assert len(dets) == len(flight.detections)


def test_m8n_noise_tier_selected() -> None:
    rtk = ReplayFlight(sample_block(), rtk_enabled=True, seed=3)
    m8n = ReplayFlight(sample_block(), rtk_enabled=False, seed=3)
    # Same seed, different noise tiers -> the reported poses spread much further under M8N.
    max_diff = max(abs(r.pose.lon - m.pose.lon) for r, m in zip(rtk.poses, m8n.poses, strict=True))
    assert max_diff > 1e-5  # ~1 m of longitude; RTK sigma is cm, M8N sigma is metres
