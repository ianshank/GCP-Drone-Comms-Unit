"""Pixel -> local NED projection for LANDING_TARGET (pure, hardware-free, no numpy).

Mirrors the flat-ground ray-cast in ``meshsa.cv.geo.project_to_ground`` (kept independent
because ``jetson_yolo_gcs`` must not import meshsa). Returns the target position **relative
to the vehicle** in NED metres. FOV is in radians to match ``MavlinkSettings.fov_*_rad``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

#: At/near/above the horizon the flat-earth range is unbounded -> unusable.
_MIN_DEPRESSION_DEG = 0.1


@dataclass(frozen=True)
class CameraFov:
    """Image size (px) and horizontal/vertical field of view (radians)."""

    img_w: int
    img_h: int
    h_fov_rad: float
    v_fov_rad: float


@dataclass(frozen=True)
class NedOffset:
    """Target position relative to the vehicle, in local NED metres (down positive)."""

    north_m: float
    east_m: float
    down_m: float


def _angle_off_axis_rad(frac: float, fov_rad: float) -> float:
    """Angle (rad) from the optical axis for a normalised offset ``frac`` in [-1, 1]."""
    return math.atan(frac * math.tan(fov_rad / 2.0))


def project_pixel_to_ned(
    cam: CameraFov,
    cx: float,
    cy: float,
    *,
    alt_agl_m: float,
    heading_deg: float,
    pitch_deg: float,
    roll_deg: float = 0.0,
) -> NedOffset | None:
    """Project pixel (cx, cy) onto the ground; ``None`` if unprojectable.

    ``pitch_deg`` is camera depression below horizontal (+ looks down; 90 = nadir);
    ``heading_deg`` is camera azimuth (0=N, CW). ``None`` when there is no usable height
    (``alt_agl_m <= 0``), the image size is degenerate (``img_w``/``img_h <= 0``), or the ray
    is at/above the horizon — so a malformed frame fail-safe suppresses the send rather than
    dividing by zero on the LANDING_TARGET path.
    """
    if alt_agl_m <= 0 or cam.img_w <= 0 or cam.img_h <= 0:
        return None
    yaw_off = math.degrees(_angle_off_axis_rad((2.0 * cx / cam.img_w) - 1.0, cam.h_fov_rad))
    pitch_off = math.degrees(_angle_off_axis_rad((2.0 * cy / cam.img_h) - 1.0, cam.v_fov_rad))
    if roll_deg:
        r = math.radians(roll_deg)
        cos_r, sin_r = math.cos(r), math.sin(r)
        yaw_off, pitch_off = (
            yaw_off * cos_r - pitch_off * sin_r,
            yaw_off * sin_r + pitch_off * cos_r,
        )
    depression_deg = pitch_deg + pitch_off
    azimuth = (heading_deg + yaw_off) % 360.0
    if depression_deg > 90.0:  # points past straight-down -> reflect onto opposite azimuth
        depression_deg = 180.0 - depression_deg
        azimuth = (azimuth + 180.0) % 360.0
    if depression_deg < _MIN_DEPRESSION_DEG:
        return None
    ground_range = alt_agl_m / math.tan(math.radians(depression_deg))
    az = math.radians(azimuth)
    return NedOffset(
        north_m=ground_range * math.cos(az),
        east_m=ground_range * math.sin(az),
        down_m=alt_agl_m,
    )
