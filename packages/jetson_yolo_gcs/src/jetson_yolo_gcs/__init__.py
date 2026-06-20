"""jetson-yolo-gcs: on-board YOLO detection -> GCS video + MAVLink LANDING_TARGET.

The public surface is import-light: importing this package pulls **no** heavy or
hardware dependency (ultralytics / opencv / pymavlink are imported lazily inside the
factories that need them), so ``import jetson_yolo_gcs`` is safe on any host.
"""

from __future__ import annotations

from .core.clock import Clock, MonotonicClock, SystemClock
from .core.config import (
    CameraSettings,
    CameraType,
    MavlinkSettings,
    Settings,
    StreamEncoder,
    StreamSettings,
    YoloSettings,
    get_settings,
)
from .core.logging import configure_logging
from .detection.base import Detection, DetectionResult, DetectorBase
from .detection.factory import backend_for_path, build_detector, detector_registry
from .mavlink.bridge import LandingTargetBridge, compute_angles
from .pipeline import Pipeline, build_pipeline
from .streaming.camera import CameraSource, Frame, build_capture_pipeline
from .streaming.gstreamer import StreamWriter, build_stream_pipeline
from .utils.fps import FpsCounter

__version__ = "0.1.0"

__all__ = [
    "Clock",
    "MonotonicClock",
    "SystemClock",
    "CameraSettings",
    "CameraType",
    "MavlinkSettings",
    "Settings",
    "StreamEncoder",
    "StreamSettings",
    "YoloSettings",
    "get_settings",
    "configure_logging",
    "Detection",
    "DetectionResult",
    "DetectorBase",
    "backend_for_path",
    "build_detector",
    "detector_registry",
    "LandingTargetBridge",
    "compute_angles",
    "Pipeline",
    "build_pipeline",
    "CameraSource",
    "Frame",
    "build_capture_pipeline",
    "StreamWriter",
    "build_stream_pipeline",
    "FpsCounter",
    "__version__",
]
