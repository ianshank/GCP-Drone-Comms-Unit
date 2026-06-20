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
