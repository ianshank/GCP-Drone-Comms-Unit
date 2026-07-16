"""Tracker abstraction: the value type and the ABC default close()."""

from __future__ import annotations

from jetson_yolo_gcs.detection.base import Detection, DetectionResult
from jetson_yolo_gcs.tracking.base import TrackedDetection, TrackerBase


class _Tracker(TrackerBase):
    def update(self, result: DetectionResult) -> tuple[TrackedDetection, ...]:
        return ()


def test_tracker_close_default_is_noop() -> None:
    assert _Tracker().close() is None


def test_tracked_detection_carries_source_and_id() -> None:
    d = Detection(class_id=0, class_name="person", confidence=0.9, bbox=(0, 0, 10, 10))
    td = TrackedDetection(detection=d, track_id=5)
    assert td.detection is d
    assert td.track_id == 5
