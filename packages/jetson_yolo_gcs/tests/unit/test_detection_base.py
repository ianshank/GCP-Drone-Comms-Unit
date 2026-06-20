"""Detection dataclass behaviour: immutability, centre, best()."""

from __future__ import annotations

import dataclasses

import pytest

from jetson_yolo_gcs.detection.base import Detection, DetectionResult


def test_detection_is_frozen() -> None:
    d = Detection(class_id=0, class_name="person", confidence=0.9, bbox=(0, 0, 10, 20))
    with pytest.raises(dataclasses.FrozenInstanceError):
        d.confidence = 0.1  # type: ignore[misc]


def test_center() -> None:
    d = Detection(class_id=0, class_name="x", confidence=0.5, bbox=(10, 20, 30, 60))
    assert d.center == (20.0, 40.0)


def test_best_picks_highest_confidence() -> None:
    a = Detection(class_id=0, class_name="a", confidence=0.3, bbox=(0, 0, 1, 1))
    b = Detection(class_id=1, class_name="b", confidence=0.8, bbox=(0, 0, 1, 1))
    result = DetectionResult(detections=(a, b), width=100, height=100)
    assert result.best() is b


def test_best_empty_is_none() -> None:
    assert DetectionResult(detections=(), width=10, height=10).best() is None
