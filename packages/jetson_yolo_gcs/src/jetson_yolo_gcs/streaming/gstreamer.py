"""Outbound GStreamer egress: pure pipeline-string builder + injectable writer.

:func:`build_stream_pipeline` is a **pure** function (fully unit-tested) that selects
an encoder element from :data:`_ENCODER_PIPELINES` (``x264`` CPU vs ``nvv4l2`` Jetson
hardware) and renders an ``appsrc -> encode -> RTP/H.264 -> udpsink`` pipeline for a
GCS (QGroundControl) to receive. The real ``cv2.VideoWriter`` egress
(:class:`GStreamerWriter`) is constructed lazily and ``# pragma: no cover``; the
pipeline plumbs frames through the :class:`StreamWriter` seam so tests inject a fake.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from ..core.config import StreamEncoder, StreamSettings

#: Encoder -> the encode + parse element fragment inserted into the pipeline.
#: ``{bitrate_kbps}`` is substituted from settings.
_ENCODER_PIPELINES: dict[StreamEncoder, str] = {
    StreamEncoder.X264: (
        "x264enc tune=zerolatency bitrate={bitrate_kbps} speed-preset=ultrafast ! "
        "video/x-h264,profile=baseline ! h264parse"
    ),
    StreamEncoder.NVV4L2: (
        "nvvidconv ! video/x-raw(memory:NVMM),format=NV12 ! "
        "nvv4l2h264enc bitrate={bitrate_bps} insert-sps-pps=true ! h264parse"
    ),
}


@runtime_checkable
class StreamWriter(Protocol):
    """Sink for encoded/streamed frames (e.g. an OpenCV GStreamer ``VideoWriter``)."""

    def write(self, frame: Any) -> None:
        """Push one frame buffer into the egress pipeline."""
        ...

    def close(self) -> None:
        """Flush and release the pipeline."""
        ...


def build_stream_pipeline(settings: StreamSettings) -> str:
    """Build the outbound ``appsrc -> encode -> RTP -> udpsink`` pipeline string.

    Pure and deterministic; raises :class:`KeyError` only if a new encoder is added to
    the enum without a corresponding entry in :data:`_ENCODER_PIPELINES`.
    """
    encoder_fragment = _ENCODER_PIPELINES[settings.encoder].format(
        bitrate_kbps=settings.bitrate_kbps,
        bitrate_bps=settings.bitrate_kbps * 1000,
    )
    return (
        "appsrc ! videoconvert ! "
        f"{encoder_fragment} ! "
        "rtph264pay config-interval=1 pt=96 ! "
        f"udpsink host={settings.host} port={settings.port}"
    )


def _default_stream_writer(
    settings: StreamSettings, *, width: int, height: int, fps: float = 30.0
) -> StreamWriter:  # pragma: no cover - real cv2 GStreamer egress
    """Build an OpenCV ``VideoWriter`` over the GStreamer egress pipeline."""
    import cv2

    pipeline = build_stream_pipeline(settings)
    writer = cv2.VideoWriter(
        pipeline,
        cv2.CAP_GSTREAMER,
        0,
        fps,
        (width, height),
    )

    class _CvWriter:
        def write(self, frame: Any) -> None:
            writer.write(frame)

        def close(self) -> None:
            writer.release()

    return _CvWriter()
