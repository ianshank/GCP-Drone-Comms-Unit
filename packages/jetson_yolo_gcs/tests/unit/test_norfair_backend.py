"""Norfair backend: id map-back, skip rules, and the heavy-dep adapters.

The map-back tests inject a fake tracker + identity ``to_detections`` so no norfair/numpy is
needed. The two default adapters (``_build_tracker`` / ``_to_norfair_detections``) are covered
directly by injecting fake ``norfair``/``numpy`` into ``sys.modules`` (no ``# pragma: no cover``).
"""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from jetson_yolo_gcs.core.config import TrackerSettings
from jetson_yolo_gcs.detection.base import Detection, DetectionResult
from jetson_yolo_gcs.tracking.base import TrackedDetection
from jetson_yolo_gcs.tracking.factory import tracker_registry
from jetson_yolo_gcs.tracking.norfair_backend import (
    NorfairTracker,
    _build_tracker,
    _to_norfair_detections,
)


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


def test_update_skips_coasting_track_from_earlier_frame() -> None:
    # Norfair's update() also returns coasting/predicted tracks not matched this frame; their
    # last_detection is from an earlier frame (not in result.detections) and must be filtered so
    # TrackedDetection never carries a stale detection.
    result = _result()
    person, _ = result.detections
    stale = Detection(class_id=9, class_name="ghost", confidence=0.4, bbox=(1, 1, 2, 2))
    fake = _FakeNorfair([[_obj(1, person), _obj(2, stale)]])
    tracker = NorfairTracker(TrackerSettings(), tracker=fake, to_detections=_identity)
    assert tracker.update(result) == (TrackedDetection(person, 1),)


def test_update_skips_object_with_no_last_detection() -> None:
    # A single object with last_detection=None must be skipped, not raise (which the pipeline
    # would swallow as a whole-frame drop) — the rest of the frame's tracks still come through.
    result = _result()
    person, _ = result.detections
    no_last = types.SimpleNamespace(id=5, last_detection=None)
    fake = _FakeNorfair([[_obj(1, person), no_last]])
    tracker = NorfairTracker(TrackerSettings(), tracker=fake, to_detections=_identity)
    assert tracker.update(result) == (TrackedDetection(person, 1),)


def test_to_norfair_detections_builds_points_and_attaches_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Exercise the real adapter (bbox-centre -> norfair.Detection with data=det ride-along) with
    # fake norfair/numpy modules, so the production map-back seam is covered without heavy deps.
    class _FakeNorfairDetection:
        def __init__(self, points: Any, data: Any) -> None:
            self.points = points
            self.data = data

    monkeypatch.setitem(
        sys.modules, "norfair", types.SimpleNamespace(Detection=_FakeNorfairDetection)
    )
    monkeypatch.setitem(
        sys.modules,
        "numpy",
        types.SimpleNamespace(array=lambda seq, dtype=None: ("array", seq, dtype)),
    )

    det = Detection(class_id=0, class_name="person", confidence=0.9, bbox=(10, 20, 30, 40))
    out = _to_norfair_detections([det])
    assert len(out) == 1
    assert out[0].data is det  # source rides along for map-back
    cx, cy = det.center  # (20.0, 30.0)
    assert out[0].points == ("array", [[cx, cy]], float)


def test_build_tracker_constructs_norfair_tracker_from_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The real _build_tracker forwards every config field to norfair.Tracker (fake-injected).
    class _FakeNorfairTracker:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

    monkeypatch.setitem(sys.modules, "norfair", types.SimpleNamespace(Tracker=_FakeNorfairTracker))

    built = _build_tracker(TrackerSettings(distance_threshold=12.0, hit_counter_max=9))
    assert built.kwargs == {  # type: ignore[attr-defined]
        "distance_function": "euclidean",
        "distance_threshold": 12.0,
        "hit_counter_max": 9,
        "initialization_delay": 3,
    }


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
