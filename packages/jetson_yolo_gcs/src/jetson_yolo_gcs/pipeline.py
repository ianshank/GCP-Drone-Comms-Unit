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
from .core.config import Settings
from .core.errors import DetectionError
from .detection.base import Detection, DetectionResult, DetectorBase
from .mavlink.bridge import LandingTargetBridge
from .streaming.camera import CameraSource
from .streaming.gstreamer import StreamWriter
from .utils.fps import FpsCounter

#: Injectable idle back-off (defaults to ``time.sleep``); tests substitute a fake.
SleepCallable = Callable[[float], None]

#: Drop counters log on the first occurrence and every Nth thereafter, so a persistent
#: fault never floods the log at frame rate (mirrors meshsa's drop-and-count pattern).
_DROP_LOG_EVERY = 100

_log = structlog.get_logger("jetson_yolo_gcs.pipeline")


def _should_log_drop(count: int) -> bool:
    """True on the 1st drop and every :data:`_DROP_LOG_EVERY` drops thereafter."""
    return count == 1 or count % _DROP_LOG_EVERY == 0


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
    ) -> None:
        self._camera = camera
        self._detector = detector
        self._stream = stream
        self._bridge = bridge
        self._target_classes = target_classes
        self._clock: Clock = clock or MonotonicClock()
        self._fps = fps or FpsCounter(clock=self._clock)
        self._stop = threading.Event()

        #: Frames dropped because detection failed recoverably (malformed output).
        self.dropped_detections = 0
        #: Frames whose egress write failed (best-effort stream; never fatal).
        self.dropped_stream = 0
        #: LANDING_TARGET messages successfully published.
        self.landing_target_published = 0
        #: Clock time of the most recent frame read (``None`` until the first frame).
        #: Drives liveness — ``fps`` alone cannot detect a stall (it only ticks on
        #: successful frames, so it reports the last good rate during an outage).
        self._last_frame_t: float | None = None

    @property
    def fps(self) -> float:
        return self._fps.fps

    def snapshot(self, *, max_age_s: float = 2.0) -> dict[str, object]:
        """Return a runtime health/metrics snapshot (pure; safe to call any time).

        ``live`` is ``True`` only if a frame was read within ``max_age_s`` — a true
        liveness signal that, unlike :attr:`fps`, goes ``False`` when the camera stalls.
        """
        last_age: float | None = None
        live = False
        if self._last_frame_t is not None:
            last_age = self._clock.now() - self._last_frame_t
            live = last_age <= max_age_s
        return {
            "fps": round(self._fps.fps, 2),
            "dropped_detections": self.dropped_detections,
            "dropped_stream": self.dropped_stream,
            "landing_target_published": self.landing_target_published,
            "last_frame_age_s": None if last_age is None else round(last_age, 3),
            "live": live,
        }

    def request_stop(self) -> None:
        """Ask :meth:`run` to exit after the current iteration (signal-safe)."""
        self._stop.set()

    def step(self) -> bool:
        """Process one frame. Returns ``True`` iff a frame was read.

        Error handling is **path-specific**: a recoverable :class:`DetectionError` drops
        the frame and continues; a stream-egress failure is best-effort (dropped); but a
        ``bridge.publish`` failure is **not** swallowed — it propagates so a broken
        LANDING_TARGET (safety) feed fails loudly rather than looking healthy. Unexpected
        detector errors (e.g. CUDA OOM, bugs) also propagate.
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
            if _should_log_drop(self.dropped_detections):
                _log.warning("detection failed; dropping frame", dropped=self.dropped_detections)
            return True

        if self._stream is not None:
            try:
                self._stream.write(frame.data)
            except Exception:  # noqa: BLE001 - egress is best-effort; never kill the loop
                self.dropped_stream += 1
                if _should_log_drop(self.dropped_stream):
                    _log.warning("stream write failed; dropping", dropped=self.dropped_stream)

        if self._bridge is not None:
            target = self._select_target(result)
            if target is not None:
                # Deliberately unguarded: a failed safety-path publish must surface.
                self._bridge.publish(target, result)
                self.landing_target_published += 1
        return True

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
        bridge = LandingTargetBridge(settings.mavlink)
        bridge.start()
    return Pipeline(
        camera=camera,
        detector=detector,
        stream=stream,
        bridge=bridge,
        target_classes=settings.mavlink.target_class_set,
    )
