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

_EARTH_R_M = 6_371_000.0
#: Crude pointing uncertainty (deg) folded into the ground error estimate.
_POINTING_UNCERTAINTY_DEG = 1.0


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
    dlon = math.degrees(east / (_EARTH_R_M * math.cos(math.radians(lat))))
    return lat + dlat, lon + dlon


def _angle_off_axis(frac: float, fov_deg: float) -> float:
    """Angle (deg) from the optical axis for a normalised offset ``frac`` in [-1, 1]."""
    return math.degrees(math.atan(frac * math.tan(math.radians(fov_deg) / 2.0)))


def relative_bearing(cx: float, cam: Camera, heading_deg: float | None = None) -> float:
    """Bearing of pixel column ``cx``. Absolute (0..360) if ``heading_deg`` is given, else
    a sensor-relative bearing where 0 is the optical axis (negative = left of centre)."""
    frac = (2.0 * cx / cam.img_w) - 1.0  # -1 left .. +1 right
    yaw_off = _angle_off_axis(frac, cam.h_fov_deg)
    if heading_deg is None:
        return yaw_off
    return (heading_deg + yaw_off) % 360.0


def project_to_ground(pose: Pose, cam: Camera, cx: float, cy: float) -> GroundFix | None:
    """Cast the ray through pixel (cx, cy) onto the flat ground; ``None`` if it misses.

    Returns a :class:`GroundFix` (lat/lon + crude ``ce_m``) or ``None`` when the ray is at
    or above the horizon, or there is no usable height (``alt_agl_m <= 0``).
    """
    if pose.alt_agl_m <= 0:
        return None
    yaw_off = _angle_off_axis((2.0 * cx / cam.img_w) - 1.0, cam.h_fov_deg)
    # Image y grows downward; a pixel below the optical axis (cy > centre) adds depression.
    pitch_off = _angle_off_axis((2.0 * cy / cam.img_h) - 1.0, cam.v_fov_deg)
    depression_deg = pose.pitch_deg + pitch_off
    if depression_deg <= 0.0:  # at/above the horizon -> no ground intersection
        return None
    ground_range = pose.alt_agl_m / math.tan(math.radians(depression_deg))
    azimuth = (pose.heading_deg + yaw_off) % 360.0
    lat, lon = destination(pose.lat, pose.lon, azimuth, ground_range)
    # Crude error: pointing uncertainty projected over the slant range, plus a small floor.
    ce_m = ground_range * math.tan(math.radians(_POINTING_UNCERTAINTY_DEG)) + 5.0
    return GroundFix(lat=lat, lon=lon, ce_m=ce_m, range_m=ground_range)
