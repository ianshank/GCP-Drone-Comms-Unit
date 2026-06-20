"""Ultralytics backend (.pt / .engine / .onnx).

The pure detection-parsing logic (turning a model's per-frame output into
:class:`DetectionResult`) is unit-tested with a fake model object; only the real
model *load* (``_load_model``) imports ``ultralytics`` and is ``# pragma: no cover``.
The model is injectable (``model=...``) so tests never touch a real weights file.
"""

from __future__ import annotations

from typing import Any

import structlog

from ..core.config import YoloSettings
from .base import Detection, DetectionResult, DetectorBase
from .factory import detector_registry

_log = structlog.get_logger("jetson_yolo_gcs.detection.ultralytics")


def _load_model(settings: YoloSettings) -> Any:  # pragma: no cover - real ultralytics load
    from ultralytics import YOLO

    model = YOLO(settings.model_path)
    return model


class UltralyticsDetector(DetectorBase):
    """Wraps an Ultralytics YOLO model behind :class:`DetectorBase`."""

    def __init__(self, settings: YoloSettings, *, model: Any | None = None) -> None:
        self._settings = settings
        self._model = model if model is not None else _load_model(settings)

    def detect(self, frame: Any) -> DetectionResult:
        results = self._model(
            frame,
            conf=self._settings.confidence,
            iou=self._settings.iou,
            imgsz=self._settings.imgsz,
            verbose=False,
        )
        result = results[0]
        names = result.names
        boxes = result.boxes
        detections: list[Detection] = []
        for i in range(len(boxes)):
            x1, y1, x2, y2 = (float(v) for v in boxes.xyxy[i])
            class_id = int(boxes.cls[i])
            detections.append(
                Detection(
                    class_id=class_id,
                    class_name=str(names[class_id]) if class_id in names else str(class_id),
                    confidence=float(boxes.conf[i]),
                    bbox=(x1, y1, x2, y2),
                )
            )
        height, width = result.orig_shape
        return DetectionResult(detections=tuple(detections), width=int(width), height=int(height))

    def close(self) -> None:
        self._model = None


@detector_registry.register("ultralytics")
def _make_ultralytics(settings: YoloSettings, **options: Any) -> UltralyticsDetector:
    return UltralyticsDetector(settings, **options)
