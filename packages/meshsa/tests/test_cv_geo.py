"""meshsa.cv.geo: pixel->ground projection + bearing degradation (pure, fakes-only)."""

import math

import pytest

from meshsa.cv.geo import Camera, Pose, destination, project_to_ground, relative_bearing

CAM = Camera(img_w=1920, img_h=1080, h_fov_deg=90.0, v_fov_deg=60.0)


def test_destination_north_and_east():
    lat, lon = destination(0.0, 0.0, bearing_deg=0.0, range_m=1113.0)  # ~0.01 deg north
    assert lat == pytest.approx(0.01, abs=1e-4)
    assert lon == pytest.approx(0.0, abs=1e-6)
    lat2, lon2 = destination(0.0, 0.0, bearing_deg=90.0, range_m=1113.0)
    assert lat2 == pytest.approx(0.0, abs=1e-6)
    assert lon2 == pytest.approx(0.01, abs=1e-4)


def test_relative_bearing_center_and_offset():
    # Centre column -> optical axis: sensor-relative 0, absolute = heading.
    assert relative_bearing(CAM.img_w / 2, CAM) == pytest.approx(0.0, abs=1e-6)
    assert relative_bearing(CAM.img_w / 2, CAM, heading_deg=100.0) == pytest.approx(100.0)
    # Normalised to [0, 360): right of centre -> small positive; left of centre -> wraps
    # toward 360 (never negative, so it satisfies the Detection.bearing_deg contract).
    assert 0.0 < relative_bearing(CAM.img_w, CAM) < 90.0
    assert relative_bearing(0, CAM) > 270.0
    assert 0.0 <= relative_bearing(0, CAM) < 360.0


def test_project_nadir_is_near_drone():
    # Steep depression (looking almost straight down) -> ground point close below.
    pose = Pose(lat=10.0, lon=20.0, alt_agl_m=100.0, heading_deg=0.0, pitch_deg=89.0)
    fix = project_to_ground(pose, CAM, CAM.img_w / 2, CAM.img_h / 2)
    assert fix is not None
    assert fix.range_m < 10.0  # ~100/tan(89deg) ~ 1.7 m
    assert fix.lat == pytest.approx(10.0, abs=1e-4)


def test_project_oblique_is_forward_of_drone():
    # 45deg depression, centre pixel, heading north -> point ~alt metres north.
    pose = Pose(lat=0.0, lon=0.0, alt_agl_m=100.0, heading_deg=0.0, pitch_deg=45.0)
    fix = project_to_ground(pose, CAM, CAM.img_w / 2, CAM.img_h / 2)
    assert fix is not None
    assert fix.range_m == pytest.approx(100.0, rel=1e-3)  # alt/tan(45)
    assert fix.lat > 0.0 and fix.lon == pytest.approx(0.0, abs=1e-6)  # north
    assert fix.ce_m > 0


def test_project_horizon_and_no_alt_return_none():
    # Looking at/above horizon -> no ground intersection.
    horizon = Pose(lat=0.0, lon=0.0, alt_agl_m=100.0, heading_deg=0.0, pitch_deg=0.0)
    assert project_to_ground(horizon, CAM, CAM.img_w / 2, 0) is None  # top pixel, level cam
    # No usable height -> None (the no-GPS/no-alt degradation).
    no_alt = Pose(lat=0.0, lon=0.0, alt_agl_m=0.0, heading_deg=0.0, pitch_deg=45.0)
    assert project_to_ground(no_alt, CAM, CAM.img_w / 2, CAM.img_h / 2) is None


def test_project_shallow_depression_returns_none():
    # A near-horizon depression (< 0.1 deg) would give an unbounded range -> None, not a
    # wild out-of-range lat/lon.
    shallow = Pose(lat=0.0, lon=0.0, alt_agl_m=100.0, heading_deg=0.0, pitch_deg=0.05)
    assert project_to_ground(shallow, CAM, CAM.img_w / 2, CAM.img_h / 2) is None


def test_destination_is_finite_near_pole():
    # cos(lat) -> 0 near the pole; the guard keeps longitude finite (no div-by-zero blowup).
    lat, lon = destination(89.9999999, 0.0, bearing_deg=90.0, range_m=100.0)
    assert math.isfinite(lat) and math.isfinite(lon)
