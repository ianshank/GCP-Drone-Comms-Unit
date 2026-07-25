"""Outbound GStreamer egress: pure pipeline-string builder + injectable writer.

:func:`build_stream_pipeline` is a **pure** function (fully unit-tested) that selects
an encoder element from :data:`_ENCODER_PIPELINES` (``x264`` CPU vs ``nvv4l2`` Jetson
hardware) and renders an ``appsrc -> encode -> RTP/H.264 -> udpsink`` pipeline for a
GCS (QGroundControl) to receive. The real ``cv2.VideoWriter`` egress
(:class:`GStreamerWriter`) is constructed lazily and ``# pragma: no cover``; the
pipeline plumbs frames through the :class:`StreamWriter` seam so tests inject a fake.

:func:`create_stream_writer` is the single activation gate: streaming is **opt-in**
(``STREAM_ENABLED=true``; unauthenticated RTP egress, ``docs/AUDIT_M2_AUTH.md`` #14),
so it returns ``None`` when disabled and logs one loud WARNING when enabled.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

import structlog

from ..core.config import StreamEncoder, StreamSettings
from ..core.errors import StreamError

_log = structlog.get_logger("jetson_yolo_gcs.streaming.gstreamer")

#: Fixed RTP/H.264 payload constants (protocol-defined, not operator-tunable):
#: 96 is the standard dynamic payload type; config-interval=1 re-sends SPS/PPS each IDR.
_RTP_PAYLOAD_TYPE = 96
_RTP_CONFIG_INTERVAL = 1

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
        f"rtph264pay config-interval={_RTP_CONFIG_INTERVAL} pt={_RTP_PAYLOAD_TYPE} ! "
        f"udpsink host={settings.host} port={settings.port}"
    )


class StreamWriterFactory(Protocol):
    """Constructor seam for the real egress writer (tests inject a fake)."""

    def __call__(
        self, settings: StreamSettings, *, width: int, height: int, fps: float
    ) -> StreamWriter:
        """Build a :class:`StreamWriter` for the given settings and frame geometry."""
        ...


def create_stream_writer(
    settings: StreamSettings,
    *,
    width: int,
    height: int,
    fps: float,
    writer_factory: StreamWriterFactory | None = None,
) -> StreamWriter | None:
    """Build the egress writer iff ``settings.enabled``; ``None`` => no stream exists.

    RTP/UDP carries no authentication or encryption, so egress is operator opt-in
    (``STREAM_ENABLED=true``; ``docs/AUDIT_M2_AUTH.md`` surface #14): the default-off
    path short-circuits before any pipeline is constructed, and the opt-in path emits
    exactly one WARNING at activation (never per frame) naming the destination.
    """
    if not settings.enabled:
        return None
    _log.warning(
        "unauthenticated plaintext RTP egress enabled by operator config "
        "(STREAM_ENABLED=true); anyone on the network path can receive this video",
        host=settings.host,
        port=settings.port,
    )
    factory: StreamWriterFactory = (
        writer_factory if writer_factory is not None else _default_stream_writer
    )
    return factory(settings, width=width, height=height, fps=fps)


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
    # Fail fast: OpenCV opens GStreamer writers lazily and silently drops frames if the
    # pipeline is invalid or GStreamer is missing. Surface that at wiring time.
    if not writer.isOpened():
        raise StreamError(f"could not open stream pipeline: {pipeline}")

    class _CvWriter:
        def write(self, frame: Any) -> None:
            writer.write(frame)

        def close(self) -> None:
            writer.release()

    return _CvWriter()
