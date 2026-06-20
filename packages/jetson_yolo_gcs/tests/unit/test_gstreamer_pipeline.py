"""Pure pipeline-string generation for capture and egress (no hardware)."""

from __future__ import annotations

from jetson_yolo_gcs.core.config import (
    CameraSettings,
    CameraType,
    StreamEncoder,
    StreamSettings,
)
from jetson_yolo_gcs.streaming.camera import build_capture_pipeline
from jetson_yolo_gcs.streaming.gstreamer import build_stream_pipeline


def test_usb_capture_pipeline() -> None:
    p = build_capture_pipeline(CameraSettings(type=CameraType.USB, source="/dev/video1"))
    assert "v4l2src device=/dev/video1" in p
    assert "appsink" in p


def test_csi_capture_pipeline() -> None:
    p = build_capture_pipeline(CameraSettings(type=CameraType.CSI, source="0"))
    assert "nvarguscamerasrc sensor-id=0" in p


def test_rtsp_capture_pipeline() -> None:
    p = build_capture_pipeline(CameraSettings(type=CameraType.RTSP, source="rtsp://cam/stream"))
    assert "rtspsrc location=rtsp://cam/stream" in p


def test_x264_stream_pipeline_uses_kbps() -> None:
    p = build_stream_pipeline(StreamSettings(encoder=StreamEncoder.X264, bitrate_kbps=2500))
    assert "x264enc" in p
    assert "bitrate=2500" in p
    assert "udpsink host=127.0.0.1 port=5600" in p


def test_nvv4l2_stream_pipeline_uses_bps() -> None:
    p = build_stream_pipeline(
        StreamSettings(encoder=StreamEncoder.NVV4L2, bitrate_kbps=4000, port=5601)
    )
    assert "nvv4l2h264enc" in p
    assert "bitrate=4000000" in p  # kbps -> bps
    assert "port=5601" in p
