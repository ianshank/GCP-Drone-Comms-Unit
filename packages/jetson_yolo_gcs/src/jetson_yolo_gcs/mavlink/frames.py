"""``LANDING_TARGET`` frame encoders (code-hygiene-modularity T-4.5).

Each encoder is a pure function from the detection geometry to the **positional argument
tuple** of pymavlink's ``landing_target_send`` — the bridge only does
``conn.mav.landing_target_send(*frame)``. Pure, so the wire layout of each MAV_FRAME is
unit-tested without a connection, and the bridge no longer carries the two layouts inline.

Arg order/values verified (2026-07) against the MAVLink LANDING_TARGET spec (message id
149, ``common.xml``) and the installed pymavlink ``landing_target_send`` signature:
positional ``time_usec, target_num, frame, angle_x, angle_y, distance, size_x, size_y``
for the BODY_FRD form, then ``x, y, z, q, type, position_valid`` for the LOCAL_NED form,
with ``q`` a ``(w, x, y, z)`` quaternion (identity = ``[1, 0, 0, 0]``) and ``type=0``
(``LANDING_TARGET_TYPE_LIGHT_BEACON``).
"""

from __future__ import annotations

from ..detection.base import Detection, DetectionResult
from ..geometry.ned import NedOffset

#: MAV_FRAME_BODY_FRD — angles are relative to the vehicle body (forward-right-down).
MAV_FRAME_BODY_FRD = 12

#: MAV_FRAME_LOCAL_NED — x/y/z are a projected North/East/Down position (PX4 precision-land).
MAV_FRAME_LOCAL_NED = 1

#: LANDING_TARGET_TYPE_LIGHT_BEACON — MAVLink target-type enum for a projected point (no beacon).
LANDING_TARGET_TYPE_LIGHT_BEACON = 0

#: Identity quaternion (w, x, y, z) — the "no rotation" orientation for a LANDING_TARGET. A
#: tuple (immutable) so the shared module constant can't be mutated in place by a call site.
IDENTITY_QUATERNION_WXYZ = (1.0, 0.0, 0.0, 0.0)

#: One ``landing_target_send`` positional argument list.
Frame = tuple[object, ...]


def compute_angles(
    detection: Detection, result: DetectionResult, *, fov_x_rad: float, fov_y_rad: float
) -> tuple[float, float]:
    """Convert a bbox centre to ``(angle_x, angle_y)`` radians about the image centre.

    Positive ``angle_x`` is right of centre, positive ``angle_y`` is below centre. A
    target dead-centre yields ``(0, 0)``.
    """
    cx, cy = detection.center
    norm_x = (cx / result.width) - 0.5 if result.width else 0.0
    norm_y = (cy / result.height) - 0.5 if result.height else 0.0
    return (norm_x * fov_x_rad, norm_y * fov_y_rad)


def encode_body_frd(
    detection: Detection,
    result: DetectionResult,
    *,
    fov_x_rad: float,
    fov_y_rad: float,
    time_usec: int,
) -> Frame:
    """The ``MAV_FRAME_BODY_FRD`` angular-offset frame (the default)."""
    angle_x, angle_y = compute_angles(detection, result, fov_x_rad=fov_x_rad, fov_y_rad=fov_y_rad)
    size_x = abs(detection.bbox[2] - detection.bbox[0]) / result.width if result.width else 0.0
    size_y = abs(detection.bbox[3] - detection.bbox[1]) / result.height if result.height else 0.0
    return (
        time_usec,
        0,  # target_num
        MAV_FRAME_BODY_FRD,
        float(angle_x),
        float(angle_y),
        0.0,  # distance (unknown)
        float(size_x * fov_x_rad),
        float(size_y * fov_y_rad),
    )


def encode_local_ned(ned: NedOffset, *, time_usec: int) -> Frame:
    """The ``MAV_FRAME_LOCAL_NED`` projected-position frame (``position_valid=1``)."""
    return (
        time_usec,
        0,  # target_num
        MAV_FRAME_LOCAL_NED,
        0.0,  # angle_x (unused in NED)
        0.0,  # angle_y (unused in NED)
        0.0,  # distance (unused in NED)
        0.0,  # size_x (unused in NED)
        0.0,  # size_y (unused in NED)
        float(ned.north_m),
        float(ned.east_m),
        float(ned.down_m),
        IDENTITY_QUATERNION_WXYZ,  # q: no rotation (w, x, y, z)
        LANDING_TARGET_TYPE_LIGHT_BEACON,
        1,  # position_valid
    )
