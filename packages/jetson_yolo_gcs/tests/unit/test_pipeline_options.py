"""Unit tests for ``PipelineDeps`` / ``PipelinePolicy`` and the options resolver (T-4.5)."""

from __future__ import annotations

import dataclasses

import pytest

from jetson_yolo_gcs.core.config import MavlinkSettings, PipelineSettings
from jetson_yolo_gcs.core.options import field_names, resolve_options
from jetson_yolo_gcs.pipeline import Pipeline, PipelineDeps, PipelinePolicy
from tests.conftest import FakeCamera, FakeClock, FakeDetector


def _deps() -> PipelineDeps:
    return PipelineDeps(camera=FakeCamera([]), detector=FakeDetector(None))


def test_pipeline_accepts_models_keywords_or_both() -> None:
    deps = _deps()
    by_models = Pipeline(deps, PipelinePolicy(drop_log_every=5))
    by_keywords = Pipeline(camera=deps.camera, detector=deps.detector, drop_log_every=5)
    mixed = Pipeline(deps, drop_log_every=5)
    for pipeline in (by_models, by_keywords, mixed):
        assert pipeline.deps.camera is deps.camera
        assert pipeline.deps.detector is deps.detector
        assert pipeline.policy == PipelinePolicy(drop_log_every=5)
        assert pipeline._drop_log_every == 5


def test_keyword_overrides_one_field_of_a_model_passed_alongside() -> None:
    clock = FakeClock()
    pipeline = Pipeline(_deps(), PipelinePolicy(fps_window=4), clock=clock, fps_window=6)
    assert pipeline.deps.clock is clock
    assert pipeline.policy.fps_window == 6
    assert pipeline._clock is clock


def test_unknown_keyword_is_a_type_error() -> None:
    with pytest.raises(TypeError, match="unexpected keyword argument\\(s\\): bogus"):
        Pipeline(_deps(), bogus=1)


def test_required_deps_are_still_required_in_keyword_form() -> None:
    with pytest.raises(TypeError):
        Pipeline(detector=FakeDetector(None))  # no camera


@pytest.mark.parametrize(
    "field, value, message",
    [
        ("liveness_timeout_s", 0.0, "liveness_timeout_s must be > 0"),
        ("drop_log_every", 0, "drop_log_every must be >= 1"),
        ("min_publish_rate_hz", 0.0, "min_publish_rate_hz must be > 0"),
        ("publish_failure_tolerance", -1, "publish_failure_tolerance must be >= 0"),
    ],
)
def test_policy_validates_its_invariants(field: str, value: object, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        PipelinePolicy(**{field: value})
    with pytest.raises(ValueError, match=message):
        Pipeline(_deps(), **{field: value})


def test_policy_defaults_are_the_settings_defaults() -> None:
    pipeline_settings, mavlink_settings = PipelineSettings(), MavlinkSettings()
    assert PipelinePolicy() == PipelinePolicy.from_settings(pipeline_settings, mavlink_settings)
    tuned = PipelinePolicy.from_settings(
        PipelineSettings(drop_log_every=7, fps_window=9), MavlinkSettings(min_publish_rate_hz=2.0)
    )
    assert (tuned.drop_log_every, tuned.fps_window, tuned.min_publish_rate_hz) == (7, 9, 2.0)


def test_models_are_frozen() -> None:
    policy = PipelinePolicy()
    with pytest.raises(dataclasses.FrozenInstanceError):
        policy.fps_window = 1  # type: ignore[misc]


def test_resolve_options_and_field_names() -> None:
    assert field_names(PipelinePolicy) >= {"fps_window", "drop_log_every"}
    base = PipelinePolicy(fps_window=4)
    assert resolve_options(PipelinePolicy, base, {}) is base
    assert resolve_options(PipelinePolicy, base, {"fps_window": 8}) == PipelinePolicy(fps_window=8)
    assert resolve_options(PipelinePolicy, None, {"drop_log_every": 3}) == PipelinePolicy(
        drop_log_every=3
    )
