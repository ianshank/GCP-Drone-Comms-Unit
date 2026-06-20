"""Camera capture and GStreamer egress (pure pipeline builders + injectable I/O)."""

from .camera import CameraSource, Frame, build_capture_pipeline
from .gstreamer import StreamWriter, build_stream_pipeline

__all__ = [
    "CameraSource",
    "Frame",
    "StreamWriter",
    "build_capture_pipeline",
    "build_stream_pipeline",
]
