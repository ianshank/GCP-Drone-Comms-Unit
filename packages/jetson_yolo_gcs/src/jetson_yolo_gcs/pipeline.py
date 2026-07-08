"""Pipeline orchestrator: camera -> detector -> (stream + LANDING_TARGET).

Assembled by dependency injection (mirrors meshsa's ``node``/``router`` style): the
camera source, detector, optional stream writer and optional MAVLink bridge are all
seams, so :meth:`Pipeline.step` is fully unit-tested with fakes and needs no hardware.
:func:`build_pipeline` wires the real components from :class:`Settings`; its
device/encoder construction is the only ``# pragma: no cover`` part.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

import structlog

from .core.clock import Clock, MonotonicClock
from .core.config import MavlinkSettings, PipelineSettings, Settings
from .core.errors import DetectionError
from .detection.base import Detection, DetectionResult, DetectorBase
from .mavlink.bridge import LandingTargetBridge
from .streaming.camera import CameraSource
from .streaming.gstreamer import StreamWriter
from .utils.fps import FpsCounter
from .utils.log_throttle import should_log_throttled

#: Injectable idle back-off (defaults to ``time.sleep``); tests substitute a fake.
SleepCallable = Callable[[float], None]

#: Per-pipeline defaults sourced from the settings models so there is a single source of truth:
#: a direct ``Pipeline(...)`` and a settings-driven ``build_pipeline`` never diverge (no magic
#: numbers, no drift). Cast pins the type for mypy since ``FieldInfo.default`` is ``Any``.
_DEFAULT_LIVENESS_TIMEOUT_S: float = float(
    PipelineSettings.model_fields["liveness_timeout_s"].default
)
_DEFAULT_DROP_LOG_EVERY: int = int(PipelineSettings.model_fields["drop_log_every"].default)
_DEFAULT_MIN_PUBLISH_RATE_HZ: float = float(
    MavlinkSettings.model_fields["min_publish_rate_hz"].default
)
_DEFAULT_PUBLISH_FAILURE_TOLERANCE: int = int(
    PipelineSettings.model_fields["publish_failure_tolerance"].default
)

_log = structlog.get_logger("jetson_yolo_gcs.pipeline")

#: Backwards-compatible alias for the shared throttle predicate (kept for existing importers).
_should_log_drop = should_log_throttled


class Pipeline:
    """Reads frames, detects, optionally streams and publishes LANDING_TARGET."""

    def __init__(
        self,
        *,
        camera: CameraSource,
        detector: DetectorBase,
        stream: StreamWriter | None = None,
        bridge: LandingTargetBridge | None = None,
        target_classes: frozenset[str] | None = None,
        fps: FpsCounter | None = None,
        clock: Clock | None = None,
        liveness_timeout_s: float = _DEFAULT_LIVENESS_TIMEOUT_S,
        drop_log_every: int = _DEFAULT_DROP_LOG_EVERY,
        min_publish_rate_hz: float = _DEFAULT_MIN_PUBLISH_RATE_HZ,
        publish_failure_tolerance: int = _DEFAULT_PUBLISH_FAILURE_TOLERANCE,
    ) -> None:
        # Enforce the class's own invariants independent of config Field bounds — a direct
        # ``Pipeline(...)`` (tests, embedders) must not be able to construct a self-inconsistent
        # loop (e.g. ``drop_log_every=0`` would divide-by-zero in the throttle).
        if liveness_timeout_s <= 0:
            raise ValueError(f"liveness_timeout_s must be > 0, got {liveness_timeout_s}")
        if drop_log_every < 1:
            raise ValueError(f"drop_log_every must be >= 1, got {drop_log_every}")
        if min_publish_rate_hz <= 0:
            raise ValueError(f"min_publish_rate_hz must be > 0, got {min_publish_rate_hz}")
        if publish_failure_tolerance < 0:
            raise ValueError(
                f"publish_failure_tolerance must be >= 0, got {publish_failure_tolerance}"
            )
        self._camera = camera
        self._detector = detector
        self._stream = stream
        self._bridge = bridge
        self._target_classes = target_classes
        self._clock: Clock = clock or MonotonicClock()
        self._fps = fps or FpsCounter(clock=self._clock)
        self._liveness_timeout_s = liveness_timeout_s
        self._drop_log_every = drop_log_every
        self._min_publish_rate_hz = min_publish_rate_hz
        self._publish_failure_tolerance = publish_failure_tolerance
        self._stop = threading.Event()

        #: Frames dropped because detection failed recoverably (malformed output).
        self.dropped_detections = 0
        #: Frames whose egress write failed (best-effort stream; never fatal).
        self.dropped_stream = 0
        #: LANDING_TARGET messages successfully published.
        self.landing_target_published = 0
        #: LANDING_TARGET sends suppressed by the fail-closed heartbeat gate.
        self.landing_target_suppressed = 0
        #: Successful publishes whose rate fell below the cadence floor — i.e. the interval
        #: since the previous publish *exceeded* ``1 / min_publish_rate_hz`` (too slow, not too
        #: fast). Observability only — the loop cannot publish faster than detections arrive.
        self.landing_target_cadence_violations = 0
        #: LANDING_TARGET publish attempts that raised (counted; escalates past tolerance).
        self.landing_target_publish_failures = 0
        #: Consecutive publish failures since the last success (drives the escalation gate).
        self._consecutive_publish_failures = 0
        #: Clock time of the most recent successful publish (``None`` until the first).
        self._last_publish_t: float | None = None
        #: Clock time of the most recent frame read (``None`` until the first frame).
        #: Drives liveness — ``fps`` alone cannot detect a stall (it only ticks on
        #: successful frames, so it reports the last good rate during an outage).
        self._last_frame_t: float | None = None

    @property
    def fps(self) -> float:
        return self._fps.fps

    def snapshot(self, *, max_age_s: float | None = None) -> dict[str, object]:
        """Return a runtime health/metrics snapshot (pure; safe to call any time).

        ``live`` is ``True`` only if a frame was read within ``max_age_s`` (defaults to the
        configured ``liveness_timeout_s``) — a true liveness signal that, unlike :attr:`fps`,
        goes ``False`` when the camera stalls.
        """
        threshold = self._liveness_timeout_s if max_age_s is None else max_age_s
        last_age: float | None = None
        live = False
        if self._last_frame_t is not None:
            last_age = self._clock.now() - self._last_frame_t
            live = last_age <= threshold
        #: ``None`` when there is no bridge or the gate is disabled; ``False`` exposes a gate
        #: that is on but has never seen a fresh heartbeat — the observable signal that a
        #: misconfigured (e.g. non-receiving) link is silently suppressing every publish.
        heartbeat_fresh: bool | None = None
        suppressed_by_reason: dict[str, int] = {}
        if self._bridge is not None:
            status = self._bridge.heartbeat_status()
            heartbeat_fresh = None if status is None else status.fresh
            #: Per-reason suppression breakdown from the bridge ("no_heartbeat"/"no_pose"/
            #: "unprojectable") — disambiguates the ``landing_target_suppressed`` total so an
            #: operator can tell a dead autopilot link from a missing/unprojectable pose.
            suppressed_by_reason = self._bridge.suppressed_snapshot()
        return {
            "fps": round(self._fps.fps, 2),
            "dropped_detections": self.dropped_detections,
            "dropped_stream": self.dropped_stream,
            "landing_target_published": self.landing_target_published,
            "landing_target_suppressed": self.landing_target_suppressed,
            "landing_target_suppressed_by_reason": suppressed_by_reason,
            "landing_target_cadence_violations": self.landing_target_cadence_violations,
            "landing_target_publish_failures": self.landing_target_publish_failures,
            "landing_target_heartbeat_fresh": heartbeat_fresh,
            "last_frame_age_s": None if last_age is None else round(last_age, 3),
            "live": live,
        }

    def request_stop(self) -> None:
        """Ask :meth:`run` to exit after the current iteration (signal-safe)."""
        self._stop.set()

    def step(self) -> bool:
        """Process one frame. Returns ``True`` iff a frame was read.

        Error handling is **path-specific**: a recoverable :class:`DetectionError` drops
        the frame and continues; a stream-egress failure is best-effort (dropped). A
        ``bridge.publish`` failure is **tolerated then escalated**: consecutive failures are
        counted and rate-limited-logged, but once they reach ``publish_failure_tolerance``
        the exception re-raises so a persistently broken LANDING_TARGET (safety) feed fails
        loudly rather than looking healthy. A single transient blip no longer kills the
        camera+stream loop. Unexpected detector errors (e.g. CUDA OOM, bugs) still propagate.
        """
        frame = self._camera.read_frame()
        if frame is None:
            return False
        self._fps.tick()
        self._last_frame_t = self._clock.now()

        try:
            result = self._detector.detect(frame.data)
        except DetectionError:
            self.dropped_detections += 1
            if _should_log_drop(self.dropped_detections, self._drop_log_every):
                _log.warning("detection failed; dropping frame", dropped=self.dropped_detections)
            return True

        if self._stream is not None:
            try:
                self._stream.write(frame.data)
            except Exception:  # noqa: BLE001 - egress is best-effort; never kill the loop
                self.dropped_stream += 1
                if _should_log_drop(self.dropped_stream, self._drop_log_every):
                    _log.warning("stream write failed; dropping", dropped=self.dropped_stream)

        if self._bridge is not None:
            # Drain any pending autopilot heartbeat into the bridge's fail-closed gate first,
            # so the publish below sees the freshest link state.
            self._bridge.poll_heartbeat()
            target = self._select_target(result)
            if target is not None:
                self._publish_target(target, result, capture_t=frame.t)
        return True

    def _publish_target(
        self, target: Detection, result: DetectionResult, *, capture_t: float
    ) -> None:
        """Publish one target through the bridge, applying the failure/cadence policy.

        A failed publish is counted and rate-limited-logged; it re-raises once the number of
        *consecutive* failures **exceeds** ``publish_failure_tolerance`` (so ``tolerance`` blips
        are tolerated and the ``tolerance + 1``-th escalates; ``tolerance == 0`` fails loud on
        the first). A send the bridge suppresses (heartbeat gate) is counted separately and is
        neither a success nor a failure — it does **not** reset the consecutive-failure streak,
        so an intermittently-fresh link with a persistently broken send still escalates.

        ``capture_t`` is the source frame's capture timestamp (:attr:`Frame.t`), forwarded to
        the bridge so ``capture_time_source="capture"`` can stamp ``time_usec`` from the frame
        rather than the wall clock at publish time (the ``"publish"`` default ignores it).
        """
        assert self._bridge is not None  # guarded by the caller
        try:
            sent = self._bridge.publish(target, result, capture_t=capture_t)
        except Exception:  # noqa: BLE001 - a publish fault is counted/tolerated, never crashes the loop
            self.landing_target_publish_failures += 1
            self._consecutive_publish_failures += 1
            if should_log_throttled(self.landing_target_publish_failures, self._drop_log_every):
                _log.warning(
                    "LANDING_TARGET publish failed",
                    failures=self.landing_target_publish_failures,
                    consecutive=self._consecutive_publish_failures,
                )
            if self._consecutive_publish_failures > self._publish_failure_tolerance:
                _log.error(
                    "LANDING_TARGET publish failing persistently; escalating",
                    consecutive=self._consecutive_publish_failures,
                    tolerance=self._publish_failure_tolerance,
                    exc_info=True,
                )
                raise
            return
        if not sent:
            # Gate suppression: not a send attempt, so leave the failure streak intact.
            self.landing_target_suppressed += 1
            return
        self._consecutive_publish_failures = 0  # reset only on an actual successful send
        self.landing_target_published += 1
        self._note_publish_cadence()

    def _note_publish_cadence(self) -> None:
        """Count a cadence violation when the interval since the last publish *exceeded* the
        max allowed gap (``1 / min_publish_rate_hz``) — i.e. the publish rate fell below the floor.
        """
        now = self._clock.now()
        if self._last_publish_t is not None and self._min_publish_rate_hz > 0:
            max_gap_s = 1.0 / self._min_publish_rate_hz
            if (now - self._last_publish_t) > max_gap_s:
                self.landing_target_cadence_violations += 1
                if _should_log_drop(self.landing_target_cadence_violations, self._drop_log_every):
                    _log.warning(
                        "LANDING_TARGET publish cadence below floor",
                        gap_s=round(now - self._last_publish_t, 3),
                        min_rate_hz=self._min_publish_rate_hz,
                        violations=self.landing_target_cadence_violations,
                    )
        self._last_publish_t = now

    def _select_target(self, result: DetectionResult) -> Detection | None:
        if self._target_classes is None:
            return result.best()
        candidates = tuple(d for d in result.detections if d.class_name in self._target_classes)
        return max(candidates, key=lambda d: d.confidence, default=None)

    def run(
        self,
        *,
        max_iterations: int | None = None,
        max_consecutive_empty: int | None = None,
        idle_poll_s: float = 0.01,
        sleep: SleepCallable | None = None,
    ) -> int:
        """Run the loop, returning the number of frames processed.

        ``max_iterations`` bounds total frames (tests / bounded runs). On an empty read
        (a transient camera timeout per the ``CameraSource`` contract) the loop sleeps
        ``idle_poll_s`` and retries; it stops only after ``max_consecutive_empty``
        *consecutive* empties (``None`` ⇒ tolerate transient gaps indefinitely — the live
        default). The loop also exits promptly when :meth:`request_stop` is called.
        ``sleep`` is injectable so tests neither wait nor busy-spin.
        """
        do_sleep: SleepCallable = sleep or time.sleep
        processed = 0
        empties = 0
        while max_iterations is None or processed < max_iterations:
            if self._stop.is_set():
                break
            if self.step():
                processed += 1
                empties = 0
                continue
            empties += 1
            if max_consecutive_empty is not None and empties >= max_consecutive_empty:
                break
            do_sleep(idle_poll_s)
        return processed

    def close(self) -> None:
        """Release camera, detector, stream, and bridge resources (best-effort, idempotent)."""
        for closer in (self._camera, self._detector, self._stream, self._bridge):
            if closer is None:
                continue
            try:
                closer.close()
            except Exception:  # noqa: BLE001 - teardown must release every resource
                _log.exception("error closing pipeline resource")


def build_pipeline(settings: Settings) -> Pipeline:  # pragma: no cover - real hardware wiring
    """Wire a :class:`Pipeline` from settings using real backends/devices."""
    from .detection.factory import build_detector
    from .streaming.camera import _default_camera_factory
    from .streaming.gstreamer import _default_stream_writer

    camera = _default_camera_factory(settings.camera)()
    detector = build_detector(settings.yolo)
    stream: StreamWriter | None = None
    if settings.stream.enabled:
        stream = _default_stream_writer(
            settings.stream,
            width=settings.camera.width,
            height=settings.camera.height,
            fps=float(settings.camera.fps),
        )
    bridge: LandingTargetBridge | None = None
    if settings.mavlink.enable_landing_target:
        bridge = LandingTargetBridge(settings.mavlink, log_every=settings.pipeline.drop_log_every)
        bridge.start()
    return Pipeline(
        camera=camera,
        detector=detector,
        stream=stream,
        bridge=bridge,
        target_classes=settings.mavlink.target_class_set,
        liveness_timeout_s=settings.pipeline.liveness_timeout_s,
        drop_log_every=settings.pipeline.drop_log_every,
        min_publish_rate_hz=settings.mavlink.min_publish_rate_hz,
        publish_failure_tolerance=settings.pipeline.publish_failure_tolerance,
    )
