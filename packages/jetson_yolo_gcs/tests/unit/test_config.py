"""Config: defaults, per-domain env prefixes, validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from jetson_yolo_gcs.core.config import (
    CameraType,
    Settings,
    StreamEncoder,
    YoloSettings,
    get_settings,
)


def test_defaults() -> None:
    s = Settings()
    assert s.yolo.model_path == "yolov8n.pt"
    assert s.camera.type is CameraType.USB
    assert s.stream.encoder is StreamEncoder.X264
    # LANDING_TARGET is off by default per the charter carve-out.
    assert s.mavlink.enable_landing_target is False


def test_env_prefixes_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YOLO_MODEL_PATH", "/models/best.engine")
    monkeypatch.setenv("YOLO_CONFIDENCE", "0.7")
    monkeypatch.setenv("CAMERA_TYPE", "csi")
    monkeypatch.setenv("STREAM_ENCODER", "nvv4l2")
    monkeypatch.setenv("MAVLINK_ENABLE_LANDING_TARGET", "true")
    s = get_settings()
    assert s.yolo.model_path == "/models/best.engine"
    assert s.yolo.confidence == 0.7
    assert s.camera.type is CameraType.CSI
    assert s.stream.encoder is StreamEncoder.NVV4L2
    assert s.mavlink.enable_landing_target is True


def test_confidence_out_of_range_rejected() -> None:
    with pytest.raises(ValidationError):
        YoloSettings(confidence=1.5)


def test_invalid_port_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STREAM_PORT", "70000")
    with pytest.raises(ValidationError):
        get_settings()


def test_target_class_set_empty_is_none() -> None:
    assert Settings().mavlink.target_class_set is None


def test_target_class_set_parses_csv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAVLINK_TARGET_CLASSES", "person, car ,,boat")
    assert get_settings().mavlink.target_class_set == frozenset({"person", "car", "boat"})


def test_mavlink_source_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAVLINK_SOURCE_SYSTEM", "42")
    monkeypatch.setenv("MAVLINK_SOURCE_COMPONENT", "7")
    s = get_settings()
    assert s.mavlink.source_system == 42
    assert s.mavlink.source_component == 7


def test_mavlink_safety_gate_defaults() -> None:
    m = Settings().mavlink
    assert m.require_heartbeat is True  # fail-closed by default
    assert m.heartbeat_timeout_s == 2.0
    assert m.min_publish_rate_hz == 10.0
    assert m.target_system == 1
    assert m.target_component == 1


def test_mavlink_safety_gate_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAVLINK_REQUIRE_HEARTBEAT", "false")
    monkeypatch.setenv("MAVLINK_HEARTBEAT_TIMEOUT_S", "1.5")
    monkeypatch.setenv("MAVLINK_MIN_PUBLISH_RATE_HZ", "20")
    monkeypatch.setenv("MAVLINK_TARGET_SYSTEM", "3")
    monkeypatch.setenv("MAVLINK_TARGET_COMPONENT", "0")
    m = get_settings().mavlink
    assert m.require_heartbeat is False
    assert m.heartbeat_timeout_s == 1.5
    assert m.min_publish_rate_hz == 20.0
    assert m.target_system == 3
    assert m.target_component == 0  # wildcard


def test_heartbeat_timeout_must_be_positive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAVLINK_HEARTBEAT_TIMEOUT_S", "0")
    with pytest.raises(ValidationError):
        get_settings()


def test_target_system_out_of_range_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAVLINK_TARGET_SYSTEM", "999")
    with pytest.raises(ValidationError):
        get_settings()


def test_pipeline_defaults_run_forever() -> None:
    s = Settings()
    assert s.pipeline.idle_poll_s == 0.01
    assert s.pipeline.max_consecutive_empty is None  # tolerate transient empties
    assert s.pipeline.liveness_timeout_s == 2.0
    assert s.pipeline.drop_log_every == 100
    assert s.pipeline.publish_failure_tolerance == 3


def test_publish_failure_tolerance_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PIPELINE_PUBLISH_FAILURE_TOLERANCE", "5")
    assert get_settings().pipeline.publish_failure_tolerance == 5


def test_publish_failure_tolerance_zero_is_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    # 0 = fail loud on the first failure (tolerate none); it is a valid, meaningful setting.
    monkeypatch.setenv("PIPELINE_PUBLISH_FAILURE_TOLERANCE", "0")
    assert get_settings().pipeline.publish_failure_tolerance == 0


def test_publish_failure_tolerance_rejects_negative(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PIPELINE_PUBLISH_FAILURE_TOLERANCE", "-1")
    with pytest.raises(ValidationError):
        get_settings()


def test_drop_log_every_must_be_positive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PIPELINE_DROP_LOG_EVERY", "0")
    with pytest.raises(ValidationError):
        get_settings()


def test_pipeline_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PIPELINE_IDLE_POLL_S", "0.5")
    monkeypatch.setenv("PIPELINE_MAX_CONSECUTIVE_EMPTY", "3")
    s = get_settings()
    assert s.pipeline.idle_poll_s == 0.5
    assert s.pipeline.max_consecutive_empty == 3


def test_rtsp_latency_default_and_override(monkeypatch: pytest.MonkeyPatch) -> None:
    assert Settings().camera.rtsp_latency_ms == 0
    monkeypatch.setenv("CAMERA_RTSP_LATENCY_MS", "200")
    assert get_settings().camera.rtsp_latency_ms == 200
