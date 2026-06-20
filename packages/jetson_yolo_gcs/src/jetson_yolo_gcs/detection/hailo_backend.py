"""Hailo-8 backend (.hef) — stub.

Registered so the factory can route ``.hef`` models, but inference is not yet
implemented: :meth:`HailoDetector.detect` raises :class:`NotImplementedError` with a
clear message. The real HailoRT device handle is injectable so the stub can be
constructed and tested without Hailo hardware; the real device open is
``# pragma: no cover``.
"""

from __future__ import annotations

from typing import Any

from ..core.config import YoloSettings
from .base import DetectionResult, DetectorBase
from .factory import detector_registry


def _open_device(settings: YoloSettings) -> Any:  # pragma: no cover - real HailoRT device
    import hailo_platform

    return hailo_platform.VDevice()


class HailoDetector(DetectorBase):
    """Placeholder Hailo backend; detection is not yet implemented."""

    def __init__(self, settings: YoloSettings, *, device: Any | None = None) -> None:
        self._settings = settings
        self._device = device

    def detect(self, frame: Any) -> DetectionResult:
        raise NotImplementedError(
            "Hailo .hef backend is a stub; implement HailoRT inference to use it"
        )


@detector_registry.register("hailo")
def _make_hailo(settings: YoloSettings, **options: Any) -> HailoDetector:
    return HailoDetector(settings, **options)
