"""Backend selection by file extension + registry dispatch (with a fake backend)."""

from __future__ import annotations

from typing import Any

import pytest

from jetson_yolo_gcs.core.config import YoloSettings
from jetson_yolo_gcs.core.errors import UnknownBackendError
from jetson_yolo_gcs.detection.base import DetectionResult, DetectorBase
from jetson_yolo_gcs.detection.factory import (
    backend_for_path,
    build_detector,
    detector_registry,
)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("yolov8n.pt", "ultralytics"),
        ("model.engine", "ultralytics"),
        ("model.onnx", "ultralytics"),
        ("model.hef", "hailo"),
        ("MODEL.PT", "ultralytics"),  # case-insensitive
    ],
)
def test_backend_for_path(path: str, expected: str) -> None:
    assert backend_for_path(path) == expected


def test_unknown_extension_raises() -> None:
    with pytest.raises(UnknownBackendError):
        backend_for_path("model.weights")


class _FakeDetector(DetectorBase):
    def detect(self, frame: Any) -> DetectionResult:
        return DetectionResult(detections=(), width=0, height=0)


@detector_registry.register("fake-test-backend")
def _make_fake(settings: YoloSettings, **_: Any) -> _FakeDetector:
    return _FakeDetector()


def test_build_detector_dispatches_to_registered_backend() -> None:
    detector = build_detector(YoloSettings(), backend="fake-test-backend")
    assert isinstance(detector, _FakeDetector)


def test_build_detector_uses_extension_when_backend_not_given() -> None:
    # .hef -> hailo stub; constructs fine, detect() is what raises.
    detector = build_detector(YoloSettings(model_path="x.hef"))
    assert detector.__class__.__name__ == "HailoDetector"
