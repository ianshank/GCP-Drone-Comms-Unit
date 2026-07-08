"""Injectable vehicle-pose seam for the LOCAL_NED LANDING_TARGET path (device I/O isolated).

``PoseSource`` is a pure protocol so the bridge unit-tests with a fake. ``MavlinkPoseSource``
drains ATTITUDE (+ an injected AGL source, e.g. a rangefinder or ``GLOBAL_POSITION_INT``
reader) from an injected pymavlink connection and reduces them into a :class:`VehiclePose`.
The connection itself is always injected (mirrors ``LandingTargetBridge``'s DI seam), so
every line here — including ``recv_match`` — is exercised by a fake in
``tests/unit/test_mavlink_pose.py``; there is no real-link-only code path to pragma.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

import structlog

_log = structlog.get_logger("jetson_yolo_gcs.mavlink.pose")


@dataclass(frozen=True)
class VehiclePose:
    """Camera pose needed to project a pixel to NED. Angles in degrees, alt in metres AGL."""

    alt_agl_m: float
    heading_deg: float
    pitch_deg: float
    roll_deg: float = 0.0


@runtime_checkable
class PoseSource(Protocol):
    def latest(self) -> VehiclePose | None: ...


class MavlinkPoseSource:
    """Reduce ATTITUDE + an injected AGL source into a :class:`VehiclePose` (best-effort).

    ``camera_depression_deg`` is the fixed camera-mount depression from config (the camera
    is assumed rigidly mounted, not gimballed) and is used verbatim as ``pitch_deg``.
    ``agl_source_m`` is a caller-supplied callable (e.g. a ``RANGEFINDER``/
    ``GLOBAL_POSITION_INT`` reader) so this module stays agnostic to which MAVLink message
    supplies altitude.
    """

    def __init__(
        self,
        *,
        connection: Any,
        camera_depression_deg: float,
        agl_source_m: Callable[[], float | None],
    ) -> None:
        self._conn = connection
        self._camera_depression_deg = camera_depression_deg
        self._agl_source_m = agl_source_m
        self._latest: VehiclePose | None = None

    def poll(self) -> bool:
        """Drain one ATTITUDE (non-blocking) and refresh the cached pose. Never raises.

        Returns ``True`` iff the cached pose was refreshed this call. A connection error,
        no pending ATTITUDE, or a not-yet-available AGL reading all yield ``False`` and
        leave any previously cached pose untouched (fail-safe: a stale pose stays available
        rather than being clobbered by a partial read).
        """
        try:
            msg = self._conn.recv_match(type="ATTITUDE", blocking=False)
        except Exception:  # noqa: BLE001 - a transient link error must not kill the caller loop
            _log.debug("pose poll error", exc_info=True)
            return False
        if msg is None:
            return False
        agl = self._agl_source_m()
        if agl is None:
            return False
        self._latest = VehiclePose(
            alt_agl_m=float(agl),
            heading_deg=math.degrees(float(msg.yaw)) % 360.0,
            pitch_deg=self._camera_depression_deg,
            roll_deg=math.degrees(float(msg.roll)),
        )
        return True

    def latest(self) -> VehiclePose | None:
        return self._latest
