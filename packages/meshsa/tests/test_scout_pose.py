"""Tests for meshsa.scout.pose.PoseFuser — attitude + terrain -> AGL-correct pose."""

from __future__ import annotations

import pytest

from meshsa.scout.pose import PoseFuser
from meshsa.scout.terrain import FlatTerrain


def test_fuse_computes_true_agl_and_depression() -> None:
    fuser = PoseFuser(FlatTerrain(50.0))  # terrain 50 m
    fused = fuser.fuse(
        lat=38.5, lon=-122.5, msl_alt_m=110.0, roll_deg=3.0, pitch_deg=0.0, yaw_deg=95.0, ts=12.0
    )
    assert fused.pose.alt_agl_m == pytest.approx(60.0)  # 110 - 50
    assert fused.pose.heading_deg == pytest.approx(95.0)
    assert fused.pose.pitch_deg == pytest.approx(90.0)  # nadir mount, level airframe
    assert fused.roll_deg == pytest.approx(3.0)
    assert fused.ts == 12.0


def test_fuse_pitch_tilts_camera() -> None:
    fuser = PoseFuser(FlatTerrain(0.0), mount_depression_deg=90.0)
    fused = fuser.fuse(
        lat=0.0, lon=0.0, msl_alt_m=60.0, roll_deg=0.0, pitch_deg=10.0, yaw_deg=0.0, ts=1.0
    )
    # Aircraft noses down 10° -> camera depression reduces to 80°.
    assert fused.pose.pitch_deg == pytest.approx(80.0)


def test_fuse_wraps_heading() -> None:
    fuser = PoseFuser(FlatTerrain(0.0))
    fused = fuser.fuse(
        lat=0.0, lon=0.0, msl_alt_m=60.0, roll_deg=0.0, pitch_deg=0.0, yaw_deg=370.0, ts=1.0
    )
    assert fused.pose.heading_deg == pytest.approx(10.0)


def test_fuse_non_positive_agl_still_returns() -> None:
    fuser = PoseFuser(FlatTerrain(100.0))
    fused = fuser.fuse(
        lat=0.0, lon=0.0, msl_alt_m=80.0, roll_deg=0.0, pitch_deg=0.0, yaw_deg=0.0, ts=1.0
    )
    assert fused.pose.alt_agl_m == pytest.approx(-20.0)  # surfaced, not silently clamped
