"""Tracker registry dispatch + lazy norfair registration (with a fake backend)."""

from __future__ import annotations

from typing import Any

import pytest

from jetson_yolo_gcs.core.config import TrackerSettings
from jetson_yolo_gcs.core.errors import UnknownComponentError
from jetson_yolo_gcs.detection.base import DetectionResult
from jetson_yolo_gcs.tracking.base import TrackedDetection, TrackerBase
from jetson_yolo_gcs.tracking.factory import build_tracker, tracker_registry


class _FakeTracker(TrackerBase):
    def update(self, result: DetectionResult) -> tuple[TrackedDetection, ...]:
        return ()


@tracker_registry.register("fake-tracker-backend")
def _make_fake(settings: TrackerSettings, **_: Any) -> _FakeTracker:
    return _FakeTracker()


def test_build_tracker_dispatches_to_registered_backend() -> None:
    tracker = build_tracker(TrackerSettings(), backend="fake-tracker-backend")
    assert isinstance(tracker, _FakeTracker)


def test_build_tracker_uses_settings_backend_when_not_given() -> None:
    tracker = build_tracker(TrackerSettings(backend="fake-tracker-backend"))
    assert isinstance(tracker, _FakeTracker)


def test_build_tracker_lazily_registers_norfair() -> None:
    # Importing the backend (triggered by build_tracker) registers the real "norfair" backend
    # without pulling the norfair library at package import.
    build_tracker(TrackerSettings(), backend="fake-tracker-backend")
    assert tracker_registry.has("norfair")


def test_build_tracker_unknown_backend_raises() -> None:
    with pytest.raises(UnknownComponentError):
        build_tracker(TrackerSettings(), backend="does-not-exist")
