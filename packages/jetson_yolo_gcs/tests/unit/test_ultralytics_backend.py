"""Ultralytics detection parsing, exercised with a fake model (no ultralytics dep)."""

from __future__ import annotations

from typing import Any

import pytest

from jetson_yolo_gcs.core.config import YoloSettings
from jetson_yolo_gcs.core.errors import DetectionError
from jetson_yolo_gcs.detection.factory import detector_registry
from jetson_yolo_gcs.detection.ultralytics_backend import UltralyticsDetector


class _FakeBoxes:
    def __init__(self, xyxy: list[list[float]], conf: list[float], cls: list[int]) -> None:
        self.xyxy = xyxy
        self.conf = conf
        self.cls = cls

    def __len__(self) -> int:
        return len(self.cls)


class _FakeResult:
    def __init__(self) -> None:
        self.boxes = _FakeBoxes(
            xyxy=[[10.0, 20.0, 110.0, 220.0], [0.0, 0.0, 5.0, 5.0]],
            conf=[0.9, 0.4],
            cls=[0, 7],  # 7 is not in names -> falls back to str(id)
        )
        self.names = {0: "person"}
        self.orig_shape = (480, 640)  # (height, width)


class _FakeModel:
    def __init__(self) -> None:
        self.kwargs: dict[str, Any] = {}

    def __call__(self, frame: Any, **kwargs: Any) -> list[_FakeResult]:
        self.kwargs = kwargs
        return [_FakeResult()]


def test_detect_parses_boxes_and_geometry() -> None:
    model = _FakeModel()
    det = UltralyticsDetector(YoloSettings(confidence=0.3, iou=0.5, imgsz=320), model=model)
    result = det.detect(object())
    assert result.width == 640
    assert result.height == 480
    assert len(result.detections) == 2
    best = result.best()
    assert best is not None
    assert best.class_name == "person"
    assert best.bbox == (10.0, 20.0, 110.0, 220.0)
    # Unknown class id falls back to its string form.
    assert result.detections[1].class_name == "7"
    # Settings are forwarded to the model call (incl. device placement).
    assert model.kwargs["conf"] == 0.3
    assert model.kwargs["imgsz"] == 320
    assert model.kwargs["device"] == "cpu"


def test_close_releases_model() -> None:
    det = UltralyticsDetector(YoloSettings(), model=_FakeModel())
    det.close()
    assert det._model is None


def test_registry_factory_accepts_injected_model() -> None:
    det = detector_registry.create("ultralytics", settings=YoloSettings(), model=_FakeModel())
    assert isinstance(det, UltralyticsDetector)


def test_empty_results_raise_detection_error() -> None:
    class _EmptyModel:
        def __call__(self, frame: Any, **kwargs: Any) -> list[Any]:
            return []

    det = UltralyticsDetector(YoloSettings(), model=_EmptyModel())
    with pytest.raises(DetectionError):
        det.detect(object())


def test_malformed_results_raise_detection_error() -> None:
    class _BadResult:
        # Missing .boxes/.names/.orig_shape -> AttributeError, wrapped as DetectionError.
        names: dict[int, str] = {}

    class _BadModel:
        def __call__(self, frame: Any, **kwargs: Any) -> list[Any]:
            return [_BadResult()]

    det = UltralyticsDetector(YoloSettings(), model=_BadModel())
    with pytest.raises(DetectionError):
        det.detect(object())
