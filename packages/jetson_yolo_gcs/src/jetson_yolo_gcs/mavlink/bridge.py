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

**Fail-closed heartbeat gate (safety hardening).** When ``require_heartbeat`` is set (the
default once landing-target is enabled), :meth:`LandingTargetBridge.publish` suppresses the
send until a *fresh* autopilot HEARTBEAT has been observed via :meth:`poll_heartbeat`. This
mirrors the commander-side ``HeartbeatHealth`` interlock. Because the gate needs to *receive*
heartbeats, the configured ``endpoint`` must be bidirectional (e.g. ``udp:``/``udpin:``); a
send-only ``udpout:`` can never receive a beat and would suppress every publish.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import structlog

from ..core.clock import Clock, SystemClock
from ..core.config import MavlinkSettings, PipelineSettings
from ..core.errors import MavlinkError
from ..detection.base import Detection, DetectionResult
from ..geometry.ned import CameraFov, project_pixel_to_ned
from ..utils.log_throttle import should_log_throttled
from .heartbeat import HeartbeatMonitor, HeartbeatReport
from .pose import PoseSource
from .timesync import _USEC_PER_SEC, TimeSync

ConnectionFactory = Callable[[], Any]

_log = structlog.get_logger("jetson_yolo_gcs.mavlink.bridge")

#: MAV_FRAME_BODY_FRD — angles are relative to the vehicle body (forward-right-down).
_MAV_FRAME_BODY_FRD = 12

#: MAV_FRAME_LOCAL_NED — x/y/z are a projected North/East/Down position (PX4 precision-land).
_MAV_FRAME_LOCAL_NED = 1

#: LANDING_TARGET_TYPE_LIGHT_BEACON — MAVLink target-type enum for a projected point (no beacon HW).
_LANDING_TARGET_TYPE_LIGHT_BEACON = 0

#: Identity quaternion (w, x, y, z) — the "no rotation" orientation for a LANDING_TARGET.
_IDENTITY_QUATERNION_WXYZ = [1.0, 0.0, 0.0, 0.0]

#: Default throttle for the "suppressed; no fresh heartbeat" warning (1st + every Nth), sourced
#: from the same config default as the pipeline's drop-log throttle so operators tune one knob.
_DEFAULT_LOG_EVERY: int = int(PipelineSettings.model_fields["drop_log_every"].default)


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

        return mavutil.mavlink_connection(
            settings.endpoint,
            source_system=settings.source_system,
            source_component=settings.source_component,
        )

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
        heartbeat: HeartbeatMonitor | None = None,
        log_every: int = _DEFAULT_LOG_EVERY,
        pose_source: PoseSource | None = None,
        timesync: TimeSync | None = None,
    ) -> None:
        if log_every < 1:
            raise ValueError(f"log_every must be >= 1, got {log_every}")
        self._settings = settings
        self._conn = connection
        self._factory = connection_factory or _default_connection_factory(settings)
        self._clock: Clock = clock or SystemClock()
        #: Vehicle-pose feed for the ``local_ned`` frame (Task 13). ``None`` when unset —
        #: the ``local_ned`` path then always fail-safe suppresses (no pose to project from).
        self._pose_source = pose_source
        #: Local->vehicle clock offset for capture-time ``time_usec`` (Task 14). ``None`` when
        #: unset — the "capture" source then uses the raw capture timestamp (no offset applied).
        self._timesync = timesync
        #: Fail-closed heartbeat gate. ``None`` disables the gate (``require_heartbeat``
        #: off); otherwise a monotonic-timebase freshness monitor sized by config.
        self._heartbeat: HeartbeatMonitor | None
        if heartbeat is not None:
            self._heartbeat = heartbeat
        elif settings.require_heartbeat:
            self._heartbeat = HeartbeatMonitor(max_age_s=settings.heartbeat_timeout_s)
        else:
            self._heartbeat = None
        #: Throttle interval for the suppression warnings (operator-tunable via
        #: ``PIPELINE_DROP_LOG_EVERY``) so a silent link never floods the log at frame rate.
        self._log_every = log_every
        #: Throttle streak across all suppression reasons (resets on a successful send) — drives
        #: the "1st + every Nth" log cadence uniformly whether the cause is heartbeat or pose.
        self._suppressed_count = 0
        #: Cumulative suppressions keyed by reason ("no_heartbeat"/"no_pose"/"unprojectable"),
        #: monotonic (never reset) for observability; exposed via :meth:`suppressed_snapshot`.
        self._suppressed: dict[str, int] = {}
        #: Last observed gate freshness, for edge-triggered lost/reacquired logging (``None``
        #: until the first observation). A fail-closed safety gate must announce transitions.
        self._last_fresh: bool | None = None

    def start(self) -> None:
        """Open the MAVLink connection if one was not injected (idempotent)."""
        if self._conn is None:
            self._conn = self._factory()

    def poll_heartbeat(self) -> bool:
        """Non-blocking drain of a pending autopilot HEARTBEAT into the freshness gate.

        Returns ``True`` iff a heartbeat from the configured ``target_system``/
        ``target_component`` (``0`` = wildcard) was consumed. With the gate disabled this is a
        no-op; otherwise the link is opened lazily (idempotent) so heartbeats can actually be
        received — without this, a factory-built bridge that was never explicitly started would
        stay fail-closed forever. A link open/read error is swallowed (a transient fault must
        never kill the caller's loop). Safe to call every pipeline step, and the pipeline calls
        it *before* ``publish`` so the gate sees the freshest link state.
        """
        if self._heartbeat is None:
            return False
        consumed = False
        try:
            if self._conn is None:
                self.start()
            if self._conn is not None:
                msg = self._conn.recv_match(type="HEARTBEAT", blocking=False)
                # The target check + beat() read duck-typed message accessors, so they stay
                # inside the guard: a malformed message must not kill the caller's loop either.
                if msg is not None and self._is_target_heartbeat(msg):
                    self._heartbeat.beat()
                    consumed = True
        except Exception:  # noqa: BLE001 - a transient link open/read/parse error must not kill the loop
            _log.debug("heartbeat poll error", exc_info=True)
        # Monitor is non-None here (guarded at the top), so freshness is well-defined.
        self._note_freshness_transition(self._heartbeat.is_fresh())
        return consumed

    def _is_target_heartbeat(self, msg: Any) -> bool:
        """True when ``msg`` is a HEARTBEAT from the configured autopilot (``0`` = any)."""
        want_sys = self._settings.target_system
        want_comp = self._settings.target_component
        return (want_sys == 0 or msg.get_srcSystem() == want_sys) and (
            want_comp == 0 or msg.get_srcComponent() == want_comp
        )

    def _note_freshness_transition(self, fresh: bool) -> None:
        """Edge-triggered log on the gate's fresh<->stale transitions (safety-critical event).

        Unlike the rate-limited suppression warning, this fires exactly once per transition so
        the operator sees precisely when the autopilot link was acquired, lost, or reacquired.
        """
        if fresh == self._last_fresh:
            return
        if self._last_fresh is None:
            if fresh:
                _log.info("autopilot heartbeat acquired; LANDING_TARGET gate open")
        elif fresh:
            _log.info("autopilot heartbeat reacquired; LANDING_TARGET gate reopened")
        else:
            _log.warning("autopilot heartbeat lost; LANDING_TARGET gate now suppressing")
        self._last_fresh = fresh

    def heartbeat_status(self) -> HeartbeatReport | None:
        """Current gate freshness report, or ``None`` when the gate is disabled.

        Lets the pipeline surface ``landing_target_heartbeat_fresh`` in its snapshot so a link
        that never delivers heartbeats is observable (not silently suppressing every publish).
        """
        return self._heartbeat.report() if self._heartbeat is not None else None

    def publish(
        self, detection: Detection, result: DetectionResult, *, capture_t: float | None = None
    ) -> bool:
        """Send one ``LANDING_TARGET`` for ``detection``.

        Returns ``True`` if a message was sent, ``False`` if the send was suppressed (feature
        disabled, the fail-closed heartbeat gate found no fresh autopilot heartbeat, or — for
        ``frame="local_ned"`` — no usable vehicle pose was available to project). A missing/
        stale heartbeat or pose is a *suppression*, not an error; a connection factory that
        yields nothing is still a loud :class:`MavlinkError` (a real fault, not a gate miss).

        ``capture_t`` is the frame's capture timestamp (seconds, same timebase as the injected
        :class:`Clock`); it feeds ``time_usec`` only when ``capture_time_source="capture"``
        (default ``"publish"`` ignores it and stamps the wall clock at send time, unchanged).
        """
        if not self._settings.enable_landing_target:
            return False
        if self._heartbeat is not None:
            report = self._heartbeat.report()  # single clock read for both fresh + reasons
            if not report.fresh:
                self._note_suppressed(
                    "no_heartbeat",
                    "LANDING_TARGET suppressed: no fresh autopilot heartbeat (fail-closed)",
                    reasons=report.reasons,
                )
                return False
        if self._conn is None:
            self.start()
        if self._conn is None:
            # start() should have opened a connection; a None here means the factory
            # produced nothing. Fail loud rather than silently dropping a safety message.
            raise MavlinkError("no MAVLink connection available to publish LANDING_TARGET")
        time_usec = self._compute_time_usec(capture_t=capture_t)
        if self._settings.frame == "local_ned":
            if not self._send_local_ned(detection, result, time_usec):
                return False
        else:
            angle_x, angle_y = compute_angles(
                detection,
                result,
                fov_x_rad=self._settings.fov_x_rad,
                fov_y_rad=self._settings.fov_y_rad,
            )
            size_x = (
                abs(detection.bbox[2] - detection.bbox[0]) / result.width if result.width else 0.0
            )
            size_y = (
                abs(detection.bbox[3] - detection.bbox[1]) / result.height if result.height else 0.0
            )
            self._send_body_frd(angle_x, angle_y, size_x, size_y, time_usec)
        self._suppressed_count = 0
        return True

    def _compute_time_usec(self, *, capture_t: float | None) -> int:
        """LANDING_TARGET.time_usec per config: publish-time wall clock, or per-frame capture time.

        The vehicle-clock offset is applied only when ``timesync_enabled`` **and** a ``TimeSync``
        is wired — so the flag is load-bearing (flipping it actually changes the stamp) rather
        than a silent no-op. Otherwise the capture path uses the raw capture timestamp, and the
        default ``"publish"`` source stamps the wall clock at send time (unchanged behaviour).
        """
        if self._settings.capture_time_source == "capture" and capture_t is not None:
            if self._settings.timesync_enabled and self._timesync is not None:
                return self._timesync.to_vehicle_usec(capture_t)
            return int(capture_t * _USEC_PER_SEC)
        return int(self._clock.now() * _USEC_PER_SEC)

    def _send_body_frd(
        self, angle_x: float, angle_y: float, size_x: float, size_y: float, time_usec: int
    ) -> None:
        """Send the ``MAV_FRAME_BODY_FRD`` angular-offset LANDING_TARGET (default, unchanged)."""
        assert self._conn is not None
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

    def _send_local_ned(
        self, detection: Detection, result: DetectionResult, time_usec: int
    ) -> bool:
        """Send a LOCAL_NED LANDING_TARGET; return ``False`` (fail-safe suppress) without a pose.

        A ``position_valid=1`` message with a bogus position is worse than none, so if there is
        no :class:`PoseSource`, no fresh pose, or the ray is unprojectable (at/above the horizon,
        no altitude), this suppresses and logs rather than sends. Arg order/values verified
        (2026-07) against the MAVLink LANDING_TARGET spec (message id 149, ``common.xml``) and
        the installed pymavlink ``landing_target_send`` signature: positional
        ``time_usec, target_num, frame, angle_x, angle_y, distance, size_x, size_y, x, y, z, q,
        type, position_valid``, with ``q`` a ``(w, x, y, z)`` quaternion (identity =
        ``[1, 0, 0, 0]``) and ``type=0`` (``LANDING_TARGET_TYPE_LIGHT_BEACON``).
        """
        pose = self._pose_source.latest() if self._pose_source is not None else None
        if pose is None:
            self._log_ned_suppressed("no_pose")
            return False
        cx, cy = detection.center
        cam = CameraFov(
            img_w=result.width,
            img_h=result.height,
            h_fov_rad=self._settings.fov_x_rad,
            v_fov_rad=self._settings.fov_y_rad,
        )
        ned = project_pixel_to_ned(
            cam,
            cx,
            cy,
            alt_agl_m=pose.alt_agl_m,
            heading_deg=pose.heading_deg,
            pitch_deg=pose.pitch_deg,
            roll_deg=pose.roll_deg,
        )
        if ned is None:
            self._log_ned_suppressed("unprojectable")
            return False
        assert self._conn is not None
        self._conn.mav.landing_target_send(
            time_usec,
            0,  # target_num
            _MAV_FRAME_LOCAL_NED,
            0.0,  # angle_x (unused in NED)
            0.0,  # angle_y (unused in NED)
            0.0,  # distance (unused in NED)
            0.0,  # size_x (unused in NED)
            0.0,  # size_y (unused in NED)
            float(ned.north_m),
            float(ned.east_m),
            float(ned.down_m),
            _IDENTITY_QUATERNION_WXYZ,  # q: no rotation (w, x, y, z)
            _LANDING_TARGET_TYPE_LIGHT_BEACON,
            1,  # position_valid
        )
        return True

    def _log_ned_suppressed(self, reason: str) -> None:
        """Record a ``local_ned`` suppression (``no_pose``/``unprojectable``) via shared accounting."""
        self._note_suppressed(
            reason, "LANDING_TARGET (local_ned) suppressed: no usable pose (fail-closed)"
        )

    def _note_suppressed(self, reason: str, message: str, **fields: object) -> None:
        """Account one suppression by ``reason`` and emit a throttled warning.

        Increments the monotonic per-reason counter (observability, via
        :meth:`suppressed_snapshot`) and the shared throttle streak, then logs on the 1st and
        every Nth suppression so a silently-suppressing link is visible without flooding at
        frame rate. Single accounting path for both the heartbeat-gate and ``local_ned`` causes,
        so the two are counted distinctly instead of sharing one opaque total.
        """
        self._suppressed[reason] = self._suppressed.get(reason, 0) + 1
        self._suppressed_count += 1
        if should_log_throttled(self._suppressed_count, self._log_every):
            _log.warning(message, suppressed=self._suppressed_count, reason=reason, **fields)

    def suppressed_snapshot(self) -> dict[str, int]:
        """Cumulative suppression counts keyed by reason (a copy — safe to expose/serialise)."""
        return dict(self._suppressed)

    def close(self) -> None:
        """Close the MAVLink connection if we own one (idempotent, best-effort)."""
        conn = self._conn
        self._conn = None
        if conn is not None:
            close = getattr(conn, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:  # noqa: BLE001 - teardown is best-effort; never raise on close
                    _log.debug("error closing MAVLink connection")
