"""Pose fusion: autopilot position + attitude + terrain -> a camera pose (Scout.1).

``meshsa.transports.mavlink_source`` yields position only (``GLOBAL_POSITION_INT``),
and its altitude is an MSL/relative datum — **not** the AGL that
:func:`meshsa.cv.geo.project_to_ground` needs. ``PoseFuser`` closes that gap: it
combines a position sample, an ``ATTITUDE`` sample, and a :class:`~meshsa.cv.geo.Terrain`
model into a :class:`~meshsa.cv.geo.Pose` with **true AGL** (``msl_alt - terrain``) plus
the camera roll to hand to the projector. Pure and side-effect free.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog

from ..cv.geo import Pose, Terrain

_log = structlog.get_logger("meshsa.scout.pose")

#: Default camera mount depression (deg): 90 = nadir (straight down) on a level airframe.
_NADIR_DEPRESSION_DEG = 90.0


@dataclass(frozen=True)
class FusedPose:
    """A projector-ready pose: the :class:`Pose` plus the camera roll to apply."""

    pose: Pose
    roll_deg: float
    ts: float


class PoseFuser:
    """Fuse position + attitude + terrain into a camera :class:`Pose`.

    ``mount_depression_deg`` is the camera's fixed depression on a level airframe
    (90 = nadir). Aircraft pitch tilts the camera: camera depression =
    ``mount_depression_deg - aircraft_pitch_deg``. Heading follows aircraft yaw;
    roll is passed through for the projector to de-rotate the image ray.
    """

    def __init__(
        self, terrain: Terrain, *, mount_depression_deg: float = _NADIR_DEPRESSION_DEG
    ) -> None:
        self._terrain = terrain
        self._mount_depression_deg = mount_depression_deg

    def fuse(
        self,
        *,
        lat: float,
        lon: float,
        msl_alt_m: float,
        roll_deg: float,
        pitch_deg: float,
        yaw_deg: float,
        ts: float,
    ) -> FusedPose:
        """Build a :class:`FusedPose` for one synchronized position+attitude sample."""
        terrain_elev = self._terrain.elevation_m(lat, lon)
        alt_agl_m = msl_alt_m - terrain_elev
        if alt_agl_m <= 0:
            _log.warning(
                "non_positive_agl",
                msl_alt_m=msl_alt_m,
                terrain_elev_m=terrain_elev,
                alt_agl_m=alt_agl_m,
            )
        depression_deg = self._mount_depression_deg - pitch_deg
        pose = Pose(
            lat=lat,
            lon=lon,
            alt_agl_m=alt_agl_m,
            heading_deg=yaw_deg % 360.0,
            pitch_deg=depression_deg,
        )
        return FusedPose(pose=pose, roll_deg=roll_deg, ts=ts)
