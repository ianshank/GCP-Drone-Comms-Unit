"""Tests for meshsa.scout.terrain — flat, gridded bilinear, and slope correction."""

from __future__ import annotations

import pytest

from meshsa.cv.geo import Camera, Pose, project_to_ground
from meshsa.scout.terrain import FlatTerrain, GriddedTerrain, GridTransform

CAM = Camera(img_w=1920, img_h=1080, h_fov_deg=70.0, v_fov_deg=42.0)


def test_flat_terrain_constant() -> None:
    t = FlatTerrain(57.0)
    assert t.elevation_m(0.0, 0.0) == 57.0
    assert t.elevation_m(38.5, -122.5) == 57.0


def test_gridded_bilinear_corners_and_center() -> None:
    # North row (row 0) = [0, 10], south row (row 1) = [20, 30]; 1°×1° cells anchored at NW.
    grid = [[0.0, 10.0], [20.0, 30.0]]
    t = GriddedTerrain(grid, GridTransform(x0=0.0, y0=1.0, dx=1.0, dy=1.0))
    assert t.elevation_m(1.0, 0.0) == pytest.approx(0.0)  # NW
    assert t.elevation_m(1.0, 1.0) == pytest.approx(10.0)  # NE
    assert t.elevation_m(0.0, 0.0) == pytest.approx(20.0)  # SW
    assert t.elevation_m(0.0, 1.0) == pytest.approx(30.0)  # SE
    assert t.elevation_m(0.5, 0.5) == pytest.approx(15.0)  # centre


def test_gridded_clamps_outside() -> None:
    grid = [[0.0, 10.0], [20.0, 30.0]]
    t = GriddedTerrain(grid, GridTransform(x0=0.0, y0=1.0, dx=1.0, dy=1.0))
    assert t.elevation_m(5.0, -5.0) == pytest.approx(0.0)  # far NW clamps to NW cell
    assert t.elevation_m(-5.0, 5.0) == pytest.approx(30.0)  # far SE clamps to SE cell


def test_gridded_rejects_bad_shape() -> None:
    with pytest.raises(ValueError):
        GriddedTerrain([], GridTransform(0.0, 0.0, 1.0, 1.0))
    with pytest.raises(ValueError):
        GriddedTerrain([[1.0, 2.0], [3.0]], GridTransform(0.0, 0.0, 1.0, 1.0))


class _LinearTerrain:
    """Elevation rises by ``slope_m_per_deg_lat`` going north (increasing lat)."""

    def __init__(self, base: float, slope_m_per_deg_lat: float, lat0: float) -> None:
        self._base = base
        self._slope = slope_m_per_deg_lat
        self._lat0 = lat0

    def elevation_m(self, lat: float, lon: float) -> float:
        return self._base + self._slope * (lat - self._lat0)


def test_slope_correction_shortens_range_when_ground_rises() -> None:
    # Camera looking north (heading 0), forward-oblique so the ray lands north (uphill).
    pose = Pose(lat=38.50, lon=-122.5, alt_agl_m=60.0, heading_deg=0.0, pitch_deg=70.0)
    cx, cy = CAM.img_w / 2, CAM.img_h * 0.75
    flat = project_to_ground(pose, CAM, cx, cy)
    # Ground rises to the north: effective AGL down-range shrinks -> shorter range.
    rising = _LinearTerrain(base=0.0, slope_m_per_deg_lat=200_000.0, lat0=pose.lat)
    corrected = project_to_ground(pose, CAM, cx, cy, terrain=rising)
    assert flat is not None and corrected is not None
    assert corrected.range_m < flat.range_m
