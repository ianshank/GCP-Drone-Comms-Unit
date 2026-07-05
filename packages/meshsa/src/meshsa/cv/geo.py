"""Geo-reference a detection pixel to a ground lat/lon (the borrowed projection math).

The DeepStream/YOLO detector process (which holds both the frame and the live drone
pose) calls these pure functions to turn a detection's pixel into a geodetic point for a
CoT marker. Kept here — pure, hardware-free, unit-tested — so the heavy detector process
just imports it (the research found no off-the-shelf reusable component; this implements
the standard flat-ground ray-cast used by e.g. roboflow/dji-aerial-georeferencing).

**Honest scope (peer-review):** geodetic projection needs camera POSE — position
(lat/lon), height above ground (``alt_agl_m``), heading, and camera depression
(``pitch_deg``) — plus FOV. A platform without GPS/attitude (e.g. a bare FPV whoop)
**cannot** be projected to lat/lon; for that case use :func:`relative_bearing` to emit a
sensor-relative bearing instead. :func:`project_to_ground` returns ``None`` when the ray
does not meet the ground (at/above the horizon) so callers degrade explicitly.

Assumptions: flat ground at ``alt_agl_m`` below the camera, level roll, rectilinear lens
(no fisheye undistortion — calibrate/undistort upstream for wide lenses). Ranges are
short enough that an equirectangular offset is adequate; ``ce`` is a crude error estimate.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

_EARTH_R_M = 6_371_000.0
#: Crude pointing uncertainty (deg) folded into the *legacy* ground error estimate
#: (used only when no explicit ``att_sigma_deg`` is supplied — see :func:`ground_error`).
_POINTING_UNCERTAINTY_DEG = 1.0
#: Legacy fixed error floor (m) added by the crude estimator when no covariance is given.
_LEGACY_ERROR_FLOOR_M = 5.0
#: Below this depression the flat-earth model is unusable (range -> very large / horizon).
_MIN_DEPRESSION_DEG = 0.1
#: Default fixed-point iterations for terrain-aware range refinement.
_DEFAULT_TERRAIN_ITERS = 2


@runtime_checkable
class Terrain(Protocol):
    """A ground-elevation model: metres above the datum at a geodetic point.

    ``FlatTerrain`` (constant) and a DEM raster both satisfy this; the projection
    stays a pure function of whatever ``Terrain`` it is handed (spec §3 seam).
    """

    def elevation_m(self, lat: float, lon: float) -> float: ...


@dataclass(frozen=True)
class Camera:
    """Pinhole-ish camera: image size (px) and horizontal/vertical field of view (deg)."""

    img_w: int
    img_h: int
    h_fov_deg: float
    v_fov_deg: float


@dataclass(frozen=True)
class Pose:
    """Camera pose. ``alt_agl_m`` is height above the ground plane; ``heading_deg`` is the
    camera azimuth (0=N, CW); ``pitch_deg`` is depression below horizontal (+ looks down)."""

    lat: float
    lon: float
    alt_agl_m: float
    heading_deg: float
    pitch_deg: float


@dataclass(frozen=True)
class GroundFix:
    """A geo-referenced detection point with a crude circular error (metres)."""

    lat: float
    lon: float
    ce_m: float
    range_m: float


def destination(lat: float, lon: float, bearing_deg: float, range_m: float) -> tuple[float, float]:
    """Point ``range_m`` from (lat, lon) along ``bearing_deg`` (equirectangular, short range)."""
    brg = math.radians(bearing_deg)
    north = range_m * math.cos(brg)
    east = range_m * math.sin(brg)
    dlat = math.degrees(north / _EARTH_R_M)
    # Guard the cos(lat) denominator near the poles (it -> 0, blowing up longitude).
    cos_lat = math.cos(math.radians(lat))
    if abs(cos_lat) < 1e-6:
        cos_lat = math.copysign(1e-6, cos_lat) if cos_lat != 0 else 1e-6
    dlon = math.degrees(east / (_EARTH_R_M * cos_lat))
    return lat + dlat, lon + dlon


def initial_bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial great-circle bearing (deg, 0=N CW) from point 1 to point 2 (inverse of
    :func:`destination`'s azimuth)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return math.degrees(math.atan2(y, x)) % 360.0


def ground_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance (m) between two points (haversine; short/mid range)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * _EARTH_R_M * math.asin(min(1.0, math.sqrt(a)))


def _angle_off_axis(frac: float, fov_deg: float) -> float:
    """Angle (deg) from the optical axis for a normalised offset ``frac`` in [-1, 1]."""
    return math.degrees(math.atan(frac * math.tan(math.radians(fov_deg) / 2.0)))


def relative_bearing(cx: float, cam: Camera, heading_deg: float | None = None) -> float:
    """Bearing of pixel column ``cx``, normalised to ``[0, 360)``.

    With ``heading_deg`` it is the absolute compass bearing; without it, a sensor-relative
    bearing measured **clockwise from the optical axis** (0 = centre, ~90 = right edge for
    a 180° FOV, left wraps toward 360). Always ``[0, 360)`` so it satisfies the
    :class:`~meshsa.models.Detection` ``bearing_deg`` contract (no negative left-of-axis
    values, which a signed convention would produce)."""
    frac = (2.0 * cx / cam.img_w) - 1.0  # -1 left .. +1 right
    yaw_off = _angle_off_axis(frac, cam.h_fov_deg)
    base = yaw_off if heading_deg is None else heading_deg + yaw_off
    return base % 360.0


def ground_error(range_m: float, pos_cep_m: float, att_sigma_deg: float) -> float:
    """Covariance-based ground circular error (m): ``pos_cep + range·tan(att_sigma)``.

    Replaces the legacy fixed-1°-plus-5 m estimate with the model from the plan:
    position CEP (RTK ~cm, M8N ~metres) plus attitude uncertainty projected over the
    slant range. Both inputs are :class:`~meshsa.config.ScoutConfig` fields, so there
    is no hidden constant here.
    """
    return pos_cep_m + range_m * math.tan(math.radians(att_sigma_deg))


def project_to_ground(
    pose: Pose,
    cam: Camera,
    cx: float,
    cy: float,
    *,
    roll_deg: float = 0.0,
    terrain: Terrain | None = None,
    pos_cep_m: float | None = None,
    att_sigma_deg: float | None = None,
    terrain_iters: int = _DEFAULT_TERRAIN_ITERS,
) -> GroundFix | None:
    """Cast the ray through pixel (cx, cy) onto the ground; ``None`` if it misses.

    Returns a :class:`GroundFix` (lat/lon + ``ce_m``) or ``None`` when the ray is at or
    above the horizon (within ``_MIN_DEPRESSION_DEG``), there is no usable height
    (``alt_agl_m <= 0``), or the terrain rises above the camera along the ray.

    Backwards-compatible extensions (all default to the original behaviour):
    - ``roll_deg`` rotates the image ray about the optical axis before projection, so a
      banking survey pass no longer mislocates the pin (default ``0.0`` = level roll).
    - ``terrain`` refines the ground intersection over a sloped surface by a few
      fixed-point iterations (default ``None`` = flat plane at ``pose.alt_agl_m``).
    - ``pos_cep_m`` / ``att_sigma_deg`` select the covariance error model
      (:func:`ground_error`); when both are ``None`` the legacy crude estimate is used.
    """
    if pose.alt_agl_m <= 0:
        return None
    yaw_off = _angle_off_axis((2.0 * cx / cam.img_w) - 1.0, cam.h_fov_deg)
    # Image y grows downward; a pixel below the optical axis (cy > centre) adds depression.
    pitch_off = _angle_off_axis((2.0 * cy / cam.img_h) - 1.0, cam.v_fov_deg)
    if roll_deg:
        # Rotate the angular offset about the optical axis (camera roll, CW positive).
        r = math.radians(roll_deg)
        cos_r, sin_r = math.cos(r), math.sin(r)
        yaw_off, pitch_off = (
            yaw_off * cos_r - pitch_off * sin_r,
            yaw_off * sin_r + pitch_off * cos_r,
        )
    depression_deg = pose.pitch_deg + pitch_off
    azimuth = (pose.heading_deg + yaw_off) % 360.0
    # A pixel that points *past* straight-down (depression > 90, e.g. below-centre on a nadir
    # camera) images the ground **behind** the camera. Reflect it to the complementary
    # depression on the opposite azimuth — the physically correct full-frame projection —
    # rather than producing a meaningless negative range.
    if depression_deg > 90.0:
        depression_deg = 180.0 - depression_deg
        azimuth = (azimuth + 180.0) % 360.0
    # At/near/above the horizon the flat-earth range is unbounded -> unusable.
    if depression_deg < _MIN_DEPRESSION_DEG:
        return None
    tan_dep = math.tan(math.radians(depression_deg))
    ground_range = pose.alt_agl_m / tan_dep
    if terrain is not None:
        # Refine over sloped ground: adjust the vertical drop by the terrain rise at the
        # current hit point relative to the camera's ground elevation, then re-solve.
        cam_elev = terrain.elevation_m(pose.lat, pose.lon)
        for _ in range(max(0, terrain_iters)):
            hit_lat, hit_lon = destination(pose.lat, pose.lon, azimuth, ground_range)
            effective_agl = pose.alt_agl_m - (terrain.elevation_m(hit_lat, hit_lon) - cam_elev)
            if effective_agl <= 0:  # terrain rises above the camera along the ray
                return None
            ground_range = effective_agl / tan_dep
    lat, lon = destination(pose.lat, pose.lon, azimuth, ground_range)
    if pos_cep_m is not None or att_sigma_deg is not None:
        ce_m = ground_error(
            ground_range,
            pos_cep_m if pos_cep_m is not None else 0.0,
            att_sigma_deg if att_sigma_deg is not None else _POINTING_UNCERTAINTY_DEG,
        )
    else:  # legacy crude estimate — preserved for existing callers/tests
        ce_m = (
            ground_range * math.tan(math.radians(_POINTING_UNCERTAINTY_DEG)) + _LEGACY_ERROR_FLOOR_M
        )
    return GroundFix(lat=lat, lon=lon, ce_m=ce_m, range_m=ground_range)
