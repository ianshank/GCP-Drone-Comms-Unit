"""Detection backends and the file-extension-driven factory."""

from .base import Detection, DetectionResult, DetectorBase
from .factory import build_detector, detector_registry

__all__ = [
    "Detection",
    "DetectionResult",
    "DetectorBase",
    "build_detector",
    "detector_registry",
]
