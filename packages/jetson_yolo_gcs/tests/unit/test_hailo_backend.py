"""Hailo stub: constructs without hardware; detect() raises NotImplementedError."""

from __future__ import annotations

import pytest

from jetson_yolo_gcs.core.config import YoloSettings
from jetson_yolo_gcs.detection.factory import build_detector
from jetson_yolo_gcs.detection.hailo_backend import HailoDetector


def test_hef_routes_to_hailo_stub() -> None:
    det = build_detector(YoloSettings(model_path="model.hef"))
    assert isinstance(det, HailoDetector)


def test_detect_not_implemented() -> None:
    det = HailoDetector(YoloSettings(), device=object())
    with pytest.raises(NotImplementedError):
        det.detect(object())
