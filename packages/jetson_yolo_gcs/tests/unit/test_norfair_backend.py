"""Norfair backend: id map-back and initializing-object skip, with an injected fake tracker.

The real norfair/numpy construction is behind ``# pragma: no cover`` seams
(``_build_tracker`` / ``_to_norfair_detections``); these tests inject both a fake tracker
and an identity ``to_detections`` so no norfair/numpy import is needed.
"""

from __future__ import annotations

import types
from typing import Any

from jetson_yolo_gcs.core.config import TrackerSettings
from jetson_yolo_gcs.detection.base import Detection, DetectionResult
from jetson_yolo_gcs.tracking.base import TrackedDetection
from jetson_yolo_gcs.tracking.factory import tracker_registry
from jetson_yolo_gcs.tracking.norfair_backend import NorfairTracker


def _result() -> DetectionResult:
    return DetectionResult(
        detections=(
            Detection(class_id=0, class_name="person", confidence=0.9, bbox=(80, 80, 120, 120)),
            Detection(class_id=2, class_name="car", confidence=0.5, bbox=(0, 0, 40, 40)),
        ),
        width=200,
        height=200,
    )


def _obj(track_id: int | None, data: Detection) -> Any:
    """A duck-typed norfair TrackedObject: ``.id`` and ``.last_detection.data``."""
    return types.SimpleNamespace(id=track_id, last_detection=types.SimpleNamespace(data=data))


class _FakeNorfair:
    """Returns a scripted list of tracked objects per ``update`` call and records inputs."""

    def __init__(self, frames: list[list[Any]]) -> None:
        self._frames = list(frames)
        self.received: list[Any] = []

    def update(self, detections: Any) -> list[Any]:
        self.received.append(detections)
        return self._frames.pop(0)


def _identity(detections: Any) -> list[Any]:
    return list(detections)


def test_update_maps_ids_back_to_source_detections() -> None:
    result = _result()
    person, car = result.detections
    fake = _FakeNorfair([[_obj(1, person), _obj(2, car)]])
    tracker = NorfairTracker(TrackerSettings(), tracker=fake, to_detections=_identity)
    assert tracker.update(result) == (TrackedDetection(person, 1), TrackedDetection(car, 2))
    # The adapter received the source detections (which then feed the fake tracker).
    assert fake.received[0] == [person, car]


def test_update_skips_initializing_object_without_id() -> None:
    result = _result()
    person, car = result.detections
    fake = _FakeNorfair([[_obj(None, person), _obj(7, car)]])
    tracker = NorfairTracker(TrackerSettings(), tracker=fake, to_detections=_identity)
    assert tracker.update(result) == (TrackedDetection(car, 7),)


def test_update_empty_when_no_tracked_objects() -> None:
    result = _result()
    fake = _FakeNorfair([[]])
    tracker = NorfairTracker(TrackerSettings(), tracker=fake, to_detections=_identity)
    assert tracker.update(result) == ()


def test_close_releases_tracker() -> None:
    tracker = NorfairTracker(TrackerSettings(), tracker=_FakeNorfair([]), to_detections=_identity)
    tracker.close()
    assert tracker._tracker is None


def test_registered_factory_builds_with_injected_seams() -> None:
    result = _result()
    person, _ = result.detections
    fake = _FakeNorfair([[_obj(3, person)]])
    tracker = tracker_registry.create(
        "norfair", settings=TrackerSettings(), tracker=fake, to_detections=_identity
    )
    assert isinstance(tracker, NorfairTracker)
    assert tracker.update(result) == (TrackedDetection(person, 3),)
