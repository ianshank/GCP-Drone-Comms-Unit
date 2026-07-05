"""Terrain models behind the :class:`~meshsa.cv.geo.Terrain` seam (spec §3, Scout.1).

``FlatTerrain`` is a constant plane (the flat-earth default). ``GriddedTerrain`` does
pure-Python bilinear interpolation over an elevation grid + affine transform — fully
testable with an in-memory grid and **no third-party dependency**. ``load_dem`` is the
only rasterio touch-point: a thin, lazy loader that reads a GeoTIFF into a grid and
returns a ``GriddedTerrain``; the file open is ``# pragma: no cover`` (I/O glue, per
CHARTER Invariant 6), so the interpolation math stays covered without rasterio installed.

The affine ``transform`` maps ``(lon, lat) -> (col, row)`` as
``col = (lon - x0) / dx``, ``row = (y0 - lat) / dy`` with ``dx, dy > 0`` (north-up),
matching a standard GeoTIFF where row 0 is the northern edge.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import structlog

from ..cv.geo import Terrain

_log = structlog.get_logger("meshsa.scout.terrain")


@dataclass(frozen=True)
class GridTransform:
    """North-up affine mapping geodetic coordinates to fractional grid indices."""

    x0: float  # longitude of the western edge (grid column 0)
    y0: float  # latitude of the northern edge (grid row 0)
    dx: float  # degrees longitude per column (> 0)
    dy: float  # degrees latitude per row (> 0)

    def to_indices(self, lat: float, lon: float) -> tuple[float, float]:
        """Return fractional ``(row, col)`` for a geodetic point."""
        return (self.y0 - lat) / self.dy, (lon - self.x0) / self.dx


class FlatTerrain:
    """Constant-elevation plane — the flat-earth default (``mean_elev_m``)."""

    def __init__(self, mean_elev_m: float) -> None:
        self.mean_elev_m = mean_elev_m

    def elevation_m(self, lat: float, lon: float) -> float:
        return self.mean_elev_m


class GriddedTerrain:
    """Bilinear elevation lookup over a 2-D grid (row-major, north-up).

    ``grid[r][c]`` is the elevation at row ``r`` (north→south), column ``c``
    (west→east). Queries outside the grid clamp to the nearest edge cell.
    """

    def __init__(self, grid: Sequence[Sequence[float]], transform: GridTransform) -> None:
        if not grid or not grid[0]:
            raise ValueError("grid must be non-empty")
        self._grid = [list(map(float, row)) for row in grid]
        self._rows = len(self._grid)
        self._cols = len(self._grid[0])
        if any(len(row) != self._cols for row in self._grid):
            raise ValueError("grid rows must be equal length")
        self.transform = transform

    def _clampi(self, i: int, hi: int) -> int:
        return 0 if i < 0 else (hi if i > hi else i)

    def elevation_m(self, lat: float, lon: float) -> float:
        rf, cf = self.transform.to_indices(lat, lon)
        r0 = self._clampi(int(rf) if rf >= 0 else int(rf) - 1, self._rows - 1)
        c0 = self._clampi(int(cf) if cf >= 0 else int(cf) - 1, self._cols - 1)
        r1 = self._clampi(r0 + 1, self._rows - 1)
        c1 = self._clampi(c0 + 1, self._cols - 1)
        # Fractional weights, clamped to [0, 1] so out-of-grid queries hold the edge value.
        fr = 0.0 if rf <= 0 else (1.0 if rf >= self._rows - 1 else rf - r0)
        fc = 0.0 if cf <= 0 else (1.0 if cf >= self._cols - 1 else cf - c0)
        top = self._grid[r0][c0] * (1 - fc) + self._grid[r0][c1] * fc
        bot = self._grid[r1][c0] * (1 - fc) + self._grid[r1][c1] * fc
        return top * (1 - fr) + bot * fr


def grid_from_band(band: Any, width: int, height: int) -> list[list[float]]:
    """Convert an indexable ``band[r][c]`` raster into a plain float grid (pure, tested).

    Extracted from :func:`load_dem` so the array-shaping logic is exercised by tests with an
    in-memory band, leaving only the ``rasterio`` file open itself as ``# pragma: no cover``.
    """
    return [[float(band[r][c]) for c in range(width)] for r in range(height)]


def load_dem(path: str) -> GriddedTerrain:
    """Load a GeoTIFF DEM into a :class:`GriddedTerrain` (lazy ``rasterio`` import).

    Only the file read is hardware/I/O glue; the grid-shaping (:func:`grid_from_band`) and the
    returned object's math (:class:`GriddedTerrain`) are pure and tested. Install with the
    ``geo`` extra: ``pip install "meshsa[geo]"``. Raises :class:`ImportError` with an install
    hint when the extra is absent.
    """
    try:
        import rasterio
    except ImportError as exc:
        raise ImportError("load_dem requires the 'geo' extra: pip install 'meshsa[geo]'") from exc
    with rasterio.open(path) as ds:  # pragma: no cover - file I/O glue (whole block)
        band: Any = ds.read(1)
        t = ds.transform
        # Prefer numpy's bulk conversion for large DEMs; fall back to the pure helper.
        grid = (
            band.tolist() if hasattr(band, "tolist") else grid_from_band(band, ds.width, ds.height)
        )
        transform = GridTransform(x0=float(t.c), y0=float(t.f), dx=float(t.a), dy=float(-t.e))
        _log.info("dem_loaded", path=path, rows=len(grid), cols=len(grid[0]))
        return GriddedTerrain(grid, transform)


def build_terrain(dem_path: str | None, mean_elev_m: float) -> Terrain:
    """Select a terrain model from config: a DEM raster when ``dem_path`` is set, else a flat
    plane at ``mean_elev_m``.

    If the ``geo`` extra (rasterio) is not installed, log a structured warning and fall back to
    the flat plane rather than crash — the pipeline stays runnable without the optional dep.
    """
    if dem_path:
        try:
            return load_dem(dem_path)
        except ImportError as exc:
            _log.warning("dem_unavailable_fallback_flat", dem_path=dem_path, error=str(exc))
    return FlatTerrain(mean_elev_m)
