"""MAVLink ``LANDING_TARGET`` publisher.

Reuses the ``meshsa.transports.mavlink_source`` injectable-connection pattern: the
pymavlink connection is injected (``connection`` / ``connection_factory``) so the
angle math and the send call are unit-tested with a fake; only the real link build
(``_default_connection_factory``) imports pymavlink and is ``# pragma: no cover``.

The bridge converts a detection's bounding-box centre into the angular offsets
(``angle_x``/``angle_y``) the autopilot expects, using the camera field of view from
config. It is **advisory** precision-landing guidance and is gated by
``MavlinkSettings.enable_landing_target`` (off by default per the charter carve-out);
it never arms, sets modes, or otherwise flies the aircraft.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import structlog

from ..core.clock import Clock, SystemClock
from ..core.config import MavlinkSettings
from ..detection.base import Detection, DetectionResult

ConnectionFactory = Callable[[], Any]

_log = structlog.get_logger("jetson_yolo_gcs.mavlink.bridge")

#: MAV_FRAME_BODY_FRD — angles are relative to the vehicle body (forward-right-down).
_MAV_FRAME_BODY_FRD = 12


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


def _default_connection_factory(settings: MavlinkSettings) -> ConnectionFactory:  # pragma: no cover
    def factory() -> Any:
        from pymavlink import mavutil

        return mavutil.mavlink_connection(settings.endpoint)

    return factory


class LandingTargetBridge:
    """Publishes ``LANDING_TARGET`` messages for detected targets."""

    def __init__(
        self,
        settings: MavlinkSettings,
        *,
        connection: Any | None = None,
        connection_factory: ConnectionFactory | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._settings = settings
        self._conn = connection
        self._factory = connection_factory or _default_connection_factory(settings)
        self._clock: Clock = clock or SystemClock()

    def start(self) -> None:
        """Open the MAVLink connection if one was not injected (idempotent)."""
        if self._conn is None:
            self._conn = self._factory()

    def publish(self, detection: Detection, result: DetectionResult) -> None:
        """Send one ``LANDING_TARGET`` for ``detection`` (no-op if disabled)."""
        if not self._settings.enable_landing_target:
            return
        if self._conn is None:
            self.start()
        angle_x, angle_y = compute_angles(
            detection,
            result,
            fov_x_rad=self._settings.fov_x_rad,
            fov_y_rad=self._settings.fov_y_rad,
        )
        size_x = abs(detection.bbox[2] - detection.bbox[0]) / result.width if result.width else 0.0
        size_y = (
            abs(detection.bbox[3] - detection.bbox[1]) / result.height if result.height else 0.0
        )
        time_usec = int(self._clock.now() * 1_000_000)
        assert self._conn is not None  # start() guarantees a live connection
        self._conn.mav.landing_target_send(
            time_usec,
            0,  # target_num
            _MAV_FRAME_BODY_FRD,
            float(angle_x),
            float(angle_y),
            0.0,  # distance (unknown)
            float(size_x * self._settings.fov_x_rad),
            float(size_y * self._settings.fov_y_rad),
        )

    def close(self) -> None:
        """Close the MAVLink connection if we own one (idempotent, best-effort)."""
        conn = self._conn
        self._conn = None
        if conn is not None:
            close = getattr(conn, "close", None)
            if callable(close):
                close()
