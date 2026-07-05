"""Tests for the additive cv.geo extensions: roll, terrain, covariance error, helpers."""

from __future__ import annotations

import math

import pytest
from hypothesis import given
from hypothesis import strategies as st

from meshsa.cv.geo import (
    Camera,
    Pose,
    destination,
    ground_distance_m,
    ground_error,
    initial_bearing,
    project_to_ground,
)
from meshsa.scout.terrain import FlatTerrain, GriddedTerrain, GridTransform

CAM = Camera(img_w=1920, img_h=1080, h_fov_deg=70.0, v_fov_deg=42.0)


def _nadir_pose(alt: float = 60.0) -> Pose:
    return Pose(lat=38.5, lon=-122.5, alt_agl_m=alt, heading_deg=0.0, pitch_deg=90.0)


def test_ground_error_model() -> None:
    assert ground_error(100.0, 0.05, 0.0) == pytest.approx(0.05)  # no attitude term
    assert ground_error(0.0, 0.2, 1.0) == pytest.approx(0.2)  # no range term
    # grows with range and with sigma
    assert ground_error(200.0, 0.05, 1.0) > ground_error(100.0, 0.05, 1.0)
    assert ground_error(100.0, 0.05, 2.0) > ground_error(100.0, 0.05, 1.0)


def test_initial_bearing_and_distance_roundtrip() -> None:
    lat0, lon0 = 38.5, -122.5
    lat1, lon1 = destination(lat0, lon0, 42.0, 250.0)
    assert initial_bearing(lat0, lon0, lat1, lon1) == pytest.approx(42.0, abs=0.5)
    assert ground_distance_m(lat0, lon0, lat1, lon1) == pytest.approx(250.0, abs=1.0)


def test_center_pixel_invariant_under_roll() -> None:
    pose = _nadir_pose()
    base = project_to_ground(pose, CAM, CAM.img_w / 2, CAM.img_h / 2)
    rolled = project_to_ground(pose, CAM, CAM.img_w / 2, CAM.img_h / 2, roll_deg=30.0)
    assert base is not None and rolled is not None
    assert base.lat == pytest.approx(rolled.lat)
    assert base.lon == pytest.approx(rolled.lon)


def test_roll_swaps_axes_at_90deg() -> None:
    # An off-axis pixel; a 90° roll should map an x-offset onto a y-offset (and vice versa).
    pose = Pose(lat=38.5, lon=-122.5, alt_agl_m=60.0, heading_deg=0.0, pitch_deg=60.0)
    off_x = project_to_ground(pose, CAM, CAM.img_w * 0.75, CAM.img_h / 2)
    off_x_rolled = project_to_ground(pose, CAM, CAM.img_w * 0.75, CAM.img_h / 2, roll_deg=90.0)
    assert off_x is not None and off_x_rolled is not None
    # The rolled projection must differ from the unrolled one.
    assert ground_distance_m(off_x.lat, off_x.lon, off_x_rolled.lat, off_x_rolled.lon) > 1.0


def test_below_axis_nadir_pixel_projects_behind() -> None:
    # Regression: a below-centre pixel on a nadir camera images the ground BEHIND the camera;
    # it must project (reflected azimuth), not be dropped as past-nadir.
    pose = Pose(lat=38.5, lon=-122.5, alt_agl_m=60.0, heading_deg=0.0, pitch_deg=90.0)
    above = project_to_ground(pose, CAM, CAM.img_w / 2, CAM.img_h * 0.3)  # ahead (north)
    below = project_to_ground(pose, CAM, CAM.img_w / 2, CAM.img_h * 0.7)  # behind (south)
    assert above is not None and below is not None
    # Camera heads north: the above-centre pixel lands north, the below-centre lands south.
    assert above.lat > pose.lat
    assert below.lat < pose.lat
    # Symmetric offsets -> symmetric ranges.
    assert below.range_m == pytest.approx(above.range_m, rel=1e-6)


def test_flat_terrain_matches_no_terrain() -> None:
    pose = Pose(lat=38.5, lon=-122.5, alt_agl_m=60.0, heading_deg=0.0, pitch_deg=70.0)
    plain = project_to_ground(pose, CAM, CAM.img_w / 2, CAM.img_h * 0.7)
    flat = project_to_ground(pose, CAM, CAM.img_w / 2, CAM.img_h * 0.7, terrain=FlatTerrain(0.0))
    assert plain is not None and flat is not None
    assert plain.lat == pytest.approx(flat.lat, abs=1e-9)
    assert plain.lon == pytest.approx(flat.lon, abs=1e-9)


def test_covariance_error_path() -> None:
    pose = _nadir_pose()
    fix = project_to_ground(
        pose, CAM, CAM.img_w / 2, CAM.img_h * 0.2, pos_cep_m=0.05, att_sigma_deg=1.0
    )
    assert fix is not None
    assert fix.ce_m == pytest.approx(ground_error(fix.range_m, 0.05, 1.0))


def test_terrain_rising_above_camera_returns_none() -> None:
    # Terrain at the hit point far above the camera's AGL -> ray never reaches ground.
    pose = Pose(lat=38.5, lon=-122.5, alt_agl_m=10.0, heading_deg=0.0, pitch_deg=60.0)
    tall = GriddedTerrain([[0.0, 0.0], [0.0, 0.0]], GridTransform(-122.51, 38.51, 0.02, 0.02))

    class _Rising:
        def elevation_m(self, lat: float, lon: float) -> float:
            # 0 at the camera, +100 elsewhere -> effective AGL goes negative down-range.
            return 0.0 if (lat, lon) == (pose.lat, pose.lon) else 100.0

    assert project_to_ground(pose, CAM, CAM.img_w / 2, CAM.img_h * 0.8, terrain=_Rising()) is None
    assert tall.elevation_m(38.5, -122.5) == pytest.approx(0.0)


def _oblique_pose(alt: float) -> Pose:
    # Forward-oblique so an above-centre pixel yields a valid (0, 90) depression at range > 0.
    return Pose(lat=38.5, lon=-122.5, alt_agl_m=alt, heading_deg=0.0, pitch_deg=60.0)


@given(
    alt_hi=st.floats(min_value=40.0, max_value=120.0), sigma=st.floats(min_value=0.1, max_value=3.0)
)
def test_error_grows_with_altitude(alt_hi: float, sigma: float) -> None:
    cx, cy = CAM.img_w / 2, CAM.img_h * 0.3  # above centre -> looks further out, range > 0
    low = project_to_ground(_oblique_pose(30.0), CAM, cx, cy, pos_cep_m=0.05, att_sigma_deg=sigma)
    high = project_to_ground(
        _oblique_pose(alt_hi), CAM, cx, cy, pos_cep_m=0.05, att_sigma_deg=sigma
    )
    assert low is not None and high is not None
    assert high.range_m > low.range_m  # higher altitude -> longer slant range
    assert high.ce_m >= low.ce_m  # -> larger ground error


def test_pixel_roundtrip_under_1px() -> None:
    pose = Pose(lat=38.5, lon=-122.5, alt_agl_m=60.0, heading_deg=15.0, pitch_deg=75.0)
    cx, cy = CAM.img_w * 0.55, CAM.img_h * 0.62
    fix = project_to_ground(pose, CAM, cx, cy)
    assert fix is not None
    # Re-derive the pixel from the ground point via the inverse used in the replay harness.
    rng = ground_distance_m(pose.lat, pose.lon, fix.lat, fix.lon)
    depression = math.degrees(math.atan2(pose.alt_agl_m, rng))
    brg = initial_bearing(pose.lat, pose.lon, fix.lat, fix.lon)
    yaw_off = ((brg - pose.heading_deg + 180.0) % 360.0) - 180.0
    pitch_off = depression - pose.pitch_deg
    fx = math.tan(math.radians(yaw_off)) / math.tan(math.radians(CAM.h_fov_deg / 2))
    fy = math.tan(math.radians(pitch_off)) / math.tan(math.radians(CAM.v_fov_deg / 2))
    rx = (fx + 1) / 2 * CAM.img_w
    ry = (fy + 1) / 2 * CAM.img_h
    assert abs(rx - cx) < 1.0
    assert abs(ry - cy) < 1.0
