"""Camera capture: the :class:`CameraSource` seam, :class:`Frame`, and pipeline build.

Mirrors ``meshsa.fpv``'s injectable camera design: :class:`CameraSource` is a
``@runtime_checkable`` Protocol and :class:`Frame` carries an ``Any`` pixel buffer so
no numpy/opencv type leaks into pure code. :func:`build_capture_pipeline` is a **pure**
string builder (fully unit-tested, no hardware) that produces a GStreamer source
pipeline for USB / CSI / RTSP cameras; the real OpenCV-backed source
(:func:`_default_camera_factory`) is imported lazily and ``# pragma: no cover``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from ..core.config import CameraSettings, CameraType
from ..core.errors import CameraError

#: Builds a :class:`CameraSource` (the real backend lives behind the factory).
CameraFactory = Callable[[], "CameraSource"]


@dataclass(frozen=True)
class Frame:
    """One captured video frame; ``data`` is the raw pixel buffer (typed ``Any``)."""

    idx: int
    t: float
    data: Any


@runtime_checkable
class CameraSource(Protocol):
    """A frame source for the pipeline.

    ``read_frame`` MUST be timeout-bounded and never block indefinitely: return the
    next :class:`Frame` or ``None`` on a bounded timeout so the loop stays responsive
    to shutdown. The default OpenCV backend is built by an injectable factory so unit
    tests use a scripted fake and require no camera.
    """

    def read_frame(self) -> Frame | None:
        """Return the next frame, or ``None`` on a bounded timeout (never blocks)."""
        ...

    def close(self) -> None:
        """Release the underlying capture device."""
        ...


def build_capture_pipeline(settings: CameraSettings) -> str:
    """Build a GStreamer capture pipeline string for the configured camera.

    Pure and deterministic (no hardware), so it is fully unit-tested. The trailing
    ``appsink`` lets OpenCV's ``VideoCapture(..., cv2.CAP_GSTREAMER)`` read frames.
    """
    caps = f"width={settings.width},height={settings.height},framerate={settings.fps}/1"
    if settings.type is CameraType.USB:
        return (
            f"v4l2src device={settings.source} ! "
            f"video/x-raw,{caps} ! videoconvert ! "
            "video/x-raw,format=BGR ! appsink drop=true max-buffers=1"
        )
    if settings.type is CameraType.CSI:
        return (
            f"nvarguscamerasrc sensor-id={settings.source} ! "
            f"video/x-raw(memory:NVMM),{caps} ! "
            "nvvidconv ! video/x-raw,format=BGRx ! videoconvert ! "
            "video/x-raw,format=BGR ! appsink drop=true max-buffers=1"
        )
    # RTSP
    return (
        f"rtspsrc location={settings.source} latency={settings.rtsp_latency_ms} ! "
        "rtph264depay ! h264parse ! avdec_h264 ! videoconvert ! "
        "video/x-raw,format=BGR ! appsink drop=true max-buffers=1"
    )


def _default_camera_factory(settings: CameraSettings) -> CameraFactory:  # pragma: no cover
    """Build an OpenCV/GStreamer-backed :class:`CameraSource` (real hardware)."""

    def factory() -> CameraSource:
        import time

        import cv2

        pipeline = build_capture_pipeline(settings)
        video_capture: Any = cv2.VideoCapture
        cap = video_capture(pipeline, cv2.CAP_GSTREAMER)
        # Fail fast: a pipeline that never opens would otherwise read () forever and,
        # with max_consecutive_empty=None, idle-loop indefinitely with no actionable error.
        if not cap.isOpened():
            cap.release()
            raise CameraError(f"could not open camera pipeline: {pipeline}")

        class _OpenCvSource:
            def __init__(self) -> None:
                self._idx = 0

            def read_frame(self) -> Frame | None:
                ok, data = cap.read()
                if not ok:
                    return None
                frame = Frame(idx=self._idx, t=time.monotonic(), data=data)
                self._idx += 1
                return frame

            def close(self) -> None:
                cap.release()

        return _OpenCvSource()

    return factory
