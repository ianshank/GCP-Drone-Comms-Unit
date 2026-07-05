"""Tests for the config-wiring helpers that connect ScoutConfig to behaviour."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from meshsa.config import ScoutConfig
from meshsa.scout import terrain as terrain_mod
from meshsa.scout.cli import camera_from_config
from meshsa.scout.pipeline import make_marker_codec
from meshsa.scout.store import InMemoryStore, SqliteStore, build_store
from meshsa.scout.terrain import FlatTerrain, build_terrain, grid_from_band, load_dem


def test_camera_from_config() -> None:
    cfg = ScoutConfig(
        camera_img_w=800, camera_img_h=600, camera_h_fov_deg=90.0, camera_v_fov_deg=50.0
    )
    cam = camera_from_config(cfg)
    assert (cam.img_w, cam.img_h, cam.h_fov_deg, cam.v_fov_deg) == (800, 600, 90.0, 50.0)


def test_build_terrain_flat_when_no_dem() -> None:
    t = build_terrain(None, 57.0)
    assert isinstance(t, FlatTerrain)
    assert t.elevation_m(0.0, 0.0) == 57.0


def test_build_terrain_uses_dem_when_set(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    sentinel = FlatTerrain(123.0)
    monkeypatch.setattr(terrain_mod, "load_dem", lambda path: sentinel)
    assert build_terrain("napa.tif", 57.0) is sentinel


def test_build_terrain_falls_back_when_geo_extra_missing(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def _boom(path: str):  # noqa: ANN202
        raise ImportError("no geo extra")

    monkeypatch.setattr(terrain_mod, "load_dem", _boom)
    t = build_terrain("napa.tif", 60.0)  # must not crash — logs + flat fallback
    assert isinstance(t, FlatTerrain)
    assert t.elevation_m(0.0, 0.0) == 60.0


def test_grid_from_band_pure() -> None:
    band = [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]
    assert grid_from_band(band, 3, 2) == [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]


def test_load_dem_without_rasterio_raises_hint() -> None:
    if importlib.util.find_spec("rasterio") is not None:
        pytest.skip("rasterio installed; the geo extra is present")
    with pytest.raises(ImportError, match="geo"):
        load_dem("nonexistent.tif")


def test_build_store_selection(tmp_path: Path) -> None:
    assert isinstance(build_store(":memory:"), InMemoryStore)
    store = build_store(str(tmp_path / "scout.db"))
    assert isinstance(store, SqliteStore)
    store.close()


def test_make_marker_codec_uses_configured_stale() -> None:
    cfg = ScoutConfig(marker_stale_s=3600.0)
    codec = make_marker_codec(cfg)
    assert codec.stale_s == 3600.0
    # And it differs from the CoT default so survey pins outlive 120 s.
    assert codec.stale_s != 120.0
