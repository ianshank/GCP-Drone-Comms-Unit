"""Row-aligned boustrophedon survey geometry + coverage analysis (spec §1 Scout.3).

``plan_boustrophedon`` generates a lawnmower path aligned to the block's row azimuth from
the camera FOV, altitude, and side overlap. ``coverage_fraction`` measures what fraction of
the block polygon the resulting swaths cover — the falsifiable "100% at side overlap" DoD.
Both are pure functions (no I/O); file export lives in :mod:`meshsa.scout.export_mission`.

Local planar frame: an equirectangular projection anchored at the block's first vertex,
rotated so ``u`` runs along the rows and ``v`` is cross-track.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import structlog

from .schemas import Block, Waypoint

_log = structlog.get_logger("meshsa.scout.survey")

_EARTH_R_M = 6_371_000.0
#: Default grid resolution (m) for the coverage sampler.
_COVERAGE_SAMPLE_M = 2.0


class _LocalFrame:
    """Equirectangular <-> local metres, rotated to the row azimuth."""

    def __init__(self, lat0: float, lon0: float, azimuth_deg: float) -> None:
        self._lat0 = lat0
        self._lon0 = lon0
        self._cos_lat0 = math.cos(math.radians(lat0))
        az = math.radians(azimuth_deg)
        self._sin_az = math.sin(az)
        self._cos_az = math.cos(az)

    def to_uv(self, lat: float, lon: float) -> tuple[float, float]:
        east = math.radians(lon - self._lon0) * self._cos_lat0 * _EARTH_R_M
        north = math.radians(lat - self._lat0) * _EARTH_R_M
        u = east * self._sin_az + north * self._cos_az  # along-row
        v = east * self._cos_az - north * self._sin_az  # cross-row
        return u, v

    def to_latlon(self, u: float, v: float) -> tuple[float, float]:
        east = u * self._sin_az + v * self._cos_az
        north = u * self._cos_az - v * self._sin_az
        lat = self._lat0 + math.degrees(north / _EARTH_R_M)
        lon = self._lon0 + math.degrees(east / (_EARTH_R_M * self._cos_lat0))
        return lat, lon


def footprints_m(cam_h_fov_deg: float, cam_v_fov_deg: float, alt_m: float) -> tuple[float, float]:
    """Ground footprint ``(cross-track, along-track)`` in metres for a nadir camera at ``alt_m``."""
    cross = 2.0 * alt_m * math.tan(math.radians(cam_h_fov_deg / 2.0))
    along = 2.0 * alt_m * math.tan(math.radians(cam_v_fov_deg / 2.0))
    return cross, along


def plan_boustrophedon(
    block: Block,
    *,
    h_fov_deg: float,
    v_fov_deg: float,
    alt_agl_m: float,
    side_overlap: float,
) -> list[Waypoint]:
    """Generate a row-aligned lawnmower path covering ``block`` at ``side_overlap``.

    Waypoints are emitted at the ends of each transect (turn points), snaking so the path
    is continuous. ``side_overlap`` in ``[0, 1)`` sets the cross-track spacing as
    ``footprint · (1 - side_overlap)``.
    """
    if not 0.0 <= side_overlap < 1.0:
        raise ValueError("side_overlap must be in [0, 1)")
    frame = _LocalFrame(block.polygon[0][0], block.polygon[0][1], block.row_azimuth_deg)
    uv = [frame.to_uv(lat, lon) for lat, lon in block.polygon]
    umin = min(p[0] for p in uv)
    umax = max(p[0] for p in uv)
    vmin = min(p[1] for p in uv)
    vmax = max(p[1] for p in uv)
    cross_m, _ = footprints_m(h_fov_deg, v_fov_deg, alt_agl_m)
    row_step = max(1.0, cross_m * (1.0 - side_overlap))
    waypoints: list[Waypoint] = []
    seq = 0
    v = vmin + row_step / 2.0
    forward = True
    while v <= vmax + row_step / 2.0:
        ends = [(umin, v), (umax, v)] if forward else [(umax, v), (umin, v)]
        for u, vv in ends:
            lat, lon = frame.to_latlon(u, vv)
            waypoints.append(Waypoint(seq=seq, lat=lat, lon=lon, alt_agl_m=alt_agl_m))
            seq += 1
        v += row_step
        forward = not forward
    _log.info("survey_planned", waypoints=len(waypoints), row_step_m=row_step)
    return waypoints


def _point_in_polygon(u: float, v: float, poly_uv: Sequence[tuple[float, float]]) -> bool:
    """Ray-casting point-in-polygon test in the local frame."""
    inside = False
    n = len(poly_uv)
    j = n - 1
    for i in range(n):
        ui, vi = poly_uv[i]
        uj, vj = poly_uv[j]
        if (vi > v) != (vj > v):
            u_cross = ui + (v - vi) / (vj - vi) * (uj - ui)
            if u < u_cross:
                inside = not inside
        j = i
    return inside


def coverage_fraction(
    block: Block,
    path: Sequence[Waypoint],
    *,
    h_fov_deg: float,
    v_fov_deg: float,
    alt_agl_m: float,
    sample_m: float = _COVERAGE_SAMPLE_M,
) -> float:
    """Fraction of the block polygon covered by the path's camera swaths (``[0, 1]``).

    A block-interior sample is covered if it lies within half the cross-track footprint of
    any transect line and within that transect's along-track extent.
    """
    if not path:
        return 0.0
    frame = _LocalFrame(block.polygon[0][0], block.polygon[0][1], block.row_azimuth_deg)
    poly_uv = [frame.to_uv(lat, lon) for lat, lon in block.polygon]
    path_uv = [frame.to_uv(w.lat, w.lon) for w in path]
    cross_m, _ = footprints_m(h_fov_deg, v_fov_deg, alt_agl_m)
    half = cross_m / 2.0
    # Transects are consecutive waypoint pairs sharing a (near-)constant v.
    transects = [(path_uv[i], path_uv[i + 1]) for i in range(0, len(path_uv) - 1, 2)]
    umin = min(p[0] for p in poly_uv)
    umax = max(p[0] for p in poly_uv)
    vmin = min(p[1] for p in poly_uv)
    vmax = max(p[1] for p in poly_uv)
    total = 0
    covered = 0
    u = umin
    while u <= umax:
        v = vmin
        while v <= vmax:
            if _point_in_polygon(u, v, poly_uv):
                total += 1
                for (u0, v0), (u1, _v1) in transects:
                    lo, hi = (u0, u1) if u0 <= u1 else (u1, u0)
                    if abs(v - v0) <= half and lo - half <= u <= hi + half:
                        covered += 1
                        break
            v += sample_m
        u += sample_m
    return covered / total if total else 0.0
