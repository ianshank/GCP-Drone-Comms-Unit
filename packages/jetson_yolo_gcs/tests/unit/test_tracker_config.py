"""TrackerSettings: defaults (off), env overrides, and Field validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from jetson_yolo_gcs.core.config import Settings, TrackerSettings


def test_tracker_defaults_are_off_and_sane() -> None:
    s = Settings()
    assert s.tracker.enabled is False
    assert s.tracker.backend == "norfair"
    assert s.tracker.distance_function == "euclidean"
    assert s.tracker.distance_threshold == 20.0
    assert s.tracker.hit_counter_max == 15
    assert s.tracker.initialization_delay == 3


def test_tracker_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRACKER_ENABLED", "true")
    monkeypatch.setenv("TRACKER_DISTANCE_THRESHOLD", "12.5")
    monkeypatch.setenv("TRACKER_INITIALIZATION_DELAY", "0")
    s = TrackerSettings()
    assert s.enabled is True
    assert s.distance_threshold == 12.5
    assert s.initialization_delay == 0  # ge=0 allows zero


@pytest.mark.parametrize(
    ("env", "value"),
    [
        ("TRACKER_DISTANCE_THRESHOLD", "0"),  # gt=0
        ("TRACKER_HIT_COUNTER_MAX", "0"),  # gt=0
        ("TRACKER_INITIALIZATION_DELAY", "-1"),  # ge=0
    ],
)
def test_tracker_rejects_out_of_range(
    monkeypatch: pytest.MonkeyPatch, env: str, value: str
) -> None:
    monkeypatch.setenv(env, value)
    with pytest.raises(ValidationError):
        TrackerSettings()
