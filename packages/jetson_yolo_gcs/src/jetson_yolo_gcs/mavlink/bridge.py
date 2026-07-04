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
from ..utils.log_throttle import should_log_throttled
from .heartbeat import HeartbeatMonitor, HeartbeatReport

ConnectionFactory = Callable[[], Any]

_log = structlog.get_logger("jetson_yolo_gcs.mavlink.bridge")

#: MAV_FRAME_BODY_FRD — angles are relative to the vehicle body (forward-right-down).
_MAV_FRAME_BODY_FRD = 12

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
    ) -> None:
        if log_every < 1:
            raise ValueError(f"log_every must be >= 1, got {log_every}")
        self._settings = settings
        self._conn = connection
        self._factory = connection_factory or _default_connection_factory(settings)
        self._clock: Clock = clock or SystemClock()
        #: Fail-closed heartbeat gate. ``None`` disables the gate (``require_heartbeat``
        #: off); otherwise a monotonic-timebase freshness monitor sized by config.
        self._heartbeat: HeartbeatMonitor | None
        if heartbeat is not None:
            self._heartbeat = heartbeat
        elif settings.require_heartbeat:
            self._heartbeat = HeartbeatMonitor(max_age_s=settings.heartbeat_timeout_s)
        else:
            self._heartbeat = None
        #: Throttle interval for the "suppressed; no fresh heartbeat" warning (operator-tunable
        #: via ``PIPELINE_DROP_LOG_EVERY``) so a silent link never floods the log at frame rate.
        self._log_every = log_every
        self._suppressed_count = 0
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

    def publish(self, detection: Detection, result: DetectionResult) -> bool:
        """Send one ``LANDING_TARGET`` for ``detection``.

        Returns ``True`` if a message was sent, ``False`` if the send was suppressed (feature
        disabled, or the fail-closed heartbeat gate found no fresh autopilot heartbeat). A
        missing/stale heartbeat is a *suppression*, not an error; a connection factory that
        yields nothing is still a loud :class:`MavlinkError` (a real fault, not a gate miss).
        """
        if not self._settings.enable_landing_target:
            return False
        if self._heartbeat is not None:
            report = self._heartbeat.report()  # single clock read for both fresh + reasons
            if not report.fresh:
                self._suppressed_count += 1
                if should_log_throttled(self._suppressed_count, self._log_every):
                    _log.warning(
                        "LANDING_TARGET suppressed: no fresh autopilot heartbeat (fail-closed)",
                        suppressed=self._suppressed_count,
                        reasons=report.reasons,
                    )
                return False
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
        if self._conn is None:
            # start() should have opened a connection; a None here means the factory
            # produced nothing. Fail loud rather than silently dropping a safety message.
            raise MavlinkError("no MAVLink connection available to publish LANDING_TARGET")
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
        self._suppressed_count = 0
        return True

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
