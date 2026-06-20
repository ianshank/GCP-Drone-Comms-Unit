"""Pipeline orchestrator: camera -> detector -> (stream + LANDING_TARGET).

Assembled by dependency injection (mirrors meshsa's ``node``/``router`` style): the
camera source, detector, optional stream writer and optional MAVLink bridge are all
seams, so :meth:`Pipeline.step` is fully unit-tested with fakes and needs no hardware.
:func:`build_pipeline` wires the real components from :class:`Settings`; its
device/encoder construction is the only ``# pragma: no cover`` part.
"""

from __future__ import annotations

import structlog

from .core.clock import Clock, MonotonicClock
from .core.config import Settings
from .detection.base import Detection, DetectionResult, DetectorBase
from .mavlink.bridge import LandingTargetBridge
from .streaming.camera import CameraSource
from .streaming.gstreamer import StreamWriter
from .utils.fps import FpsCounter

_log = structlog.get_logger("jetson_yolo_gcs.pipeline")


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

    @property
    def fps(self) -> float:
        return self._fps.fps

    def step(self) -> bool:
        """Process one frame. Returns ``False`` when the camera yields no frame."""
        frame = self._camera.read_frame()
        if frame is None:
            return False
        result = self._detector.detect(frame.data)
        if self._stream is not None:
            self._stream.write(frame.data)
        if self._bridge is not None:
            target = self._select_target(result)
            if target is not None:
                self._bridge.publish(target, result)
        self._fps.tick()
        return True

    def _select_target(self, result: DetectionResult) -> Detection | None:
        if self._target_classes is None:
            return result.best()
        candidates = tuple(d for d in result.detections if d.class_name in self._target_classes)
        return max(candidates, key=lambda d: d.confidence, default=None)

    def run(self, *, max_iterations: int | None = None) -> int:
        """Run the loop, returning the number of frames processed.

        ``max_iterations`` bounds the loop (used by tests and bounded runs); ``None``
        runs until the camera stops yielding frames.
        """
        processed = 0
        while max_iterations is None or processed < max_iterations:
            if not self.step():
                break
            processed += 1
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
