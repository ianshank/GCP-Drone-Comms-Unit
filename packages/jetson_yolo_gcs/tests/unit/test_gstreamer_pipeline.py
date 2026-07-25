"""Pure pipeline-string generation for capture and egress (no hardware)."""

from __future__ import annotations

from structlog.testing import capture_logs

from jetson_yolo_gcs.core.config import (
    CameraSettings,
    CameraType,
    StreamEncoder,
    StreamSettings,
)
from jetson_yolo_gcs.streaming.camera import build_capture_pipeline
from jetson_yolo_gcs.streaming.gstreamer import (
    StreamWriter,
    build_stream_pipeline,
    create_stream_writer,
)
from tests.conftest import FakeStreamWriter


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
    assert "latency=0" in p  # default


def test_rtsp_latency_is_configurable() -> None:
    p = build_capture_pipeline(
        CameraSettings(type=CameraType.RTSP, source="rtsp://cam/stream", rtsp_latency_ms=200)
    )
    assert "latency=200" in p


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


class _RecordingFactory:
    """Records construction calls and hands out a :class:`FakeStreamWriter`."""

    def __init__(self) -> None:
        self.calls: list[tuple[StreamSettings, int, int, float]] = []

    def __call__(
        self, settings: StreamSettings, *, width: int, height: int, fps: float
    ) -> StreamWriter:
        self.calls.append((settings, width, height, fps))
        return FakeStreamWriter()


def test_create_stream_writer_disabled_builds_nothing_and_stays_silent() -> None:
    # Default-off (AUDIT_M2_AUTH #14): no writer is constructed and no warning fires.
    factory = _RecordingFactory()
    with capture_logs() as logs:
        writer = create_stream_writer(
            StreamSettings(), width=1280, height=720, fps=30.0, writer_factory=factory
        )
    assert writer is None
    assert factory.calls == []  # the factory seam is never even invoked
    assert not any(e.get("log_level") == "warning" for e in logs)


def test_create_stream_writer_enabled_warns_once_with_host_and_port() -> None:
    settings = StreamSettings(enabled=True, host="10.0.0.7", port=5700)
    factory = _RecordingFactory()
    with capture_logs() as logs:
        writer = create_stream_writer(
            settings, width=1280, height=720, fps=30.0, writer_factory=factory
        )
    assert isinstance(writer, FakeStreamWriter)
    assert factory.calls == [(settings, 1280, 720, 30.0)]
    warnings = [
        e
        for e in logs
        if e.get("log_level") == "warning" and "unauthenticated plaintext RTP egress" in e["event"]
    ]
    assert len(warnings) == 1  # exactly one loud line at activation
    assert warnings[0]["host"] == settings.host
    assert warnings[0]["port"] == settings.port
