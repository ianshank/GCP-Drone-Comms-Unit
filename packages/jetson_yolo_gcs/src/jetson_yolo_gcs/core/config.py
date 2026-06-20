"""Configuration via pydantic-settings v2 (no magic numbers, per-domain prefixes).

Each domain is its own ``BaseSettings`` with an env prefix so operational values are
grouped and overridable from the environment or a ``.env`` file:

* ``YOLO_*``    — detection model + thresholds
* ``CAMERA_*``  — capture source / geometry
* ``STREAM_*``  — GCS video egress
* ``MAVLINK_*`` — LANDING_TARGET publisher (disabled by default)
* ``APP_*``     — top-level (logging)

The :class:`StreamEncoder` / :class:`CameraType` enums live here (core) so both the
config and the ``streaming`` layer import them in one direction (core -> streaming),
avoiding an import cycle.
"""

from __future__ import annotations

from enum import Enum

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = ".env"


class CameraType(str, Enum):
    """How the camera source string is interpreted when building a pipeline."""

    USB = "usb"
    CSI = "csi"
    RTSP = "rtsp"


class StreamEncoder(str, Enum):
    """Video encoder element for the outbound GStreamer pipeline."""

    X264 = "x264"  # CPU encoder (Orin Nano, dev hosts without HW encode)
    NVV4L2 = "nvv4l2"  # Jetson hardware encoder (Orin NX / AGX)


class YoloSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="YOLO_", env_file=_ENV_FILE, extra="ignore")

    model_path: str = "yolov8n.pt"
    confidence: float = Field(default=0.25, ge=0.0, le=1.0)
    iou: float = Field(default=0.45, ge=0.0, le=1.0)
    device: str = "cpu"
    imgsz: int = Field(default=640, gt=0)


class CameraSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CAMERA_", env_file=_ENV_FILE, extra="ignore")

    type: CameraType = CameraType.USB
    source: str = "/dev/video0"
    width: int = Field(default=1280, gt=0)
    height: int = Field(default=720, gt=0)
    fps: int = Field(default=30, gt=0)
    #: RTSP jitter-buffer latency (ms); 0 = lowest latency. Only used for CameraType.RTSP.
    rtsp_latency_ms: int = Field(default=0, ge=0)


class StreamSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="STREAM_", env_file=_ENV_FILE, extra="ignore")

    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = Field(default=5600, gt=0, le=65535)
    encoder: StreamEncoder = StreamEncoder.X264
    bitrate_kbps: int = Field(default=4000, gt=0)


class MavlinkSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MAVLINK_", env_file=_ENV_FILE, extra="ignore")

    endpoint: str = "udpout:127.0.0.1:14550"
    #: This unit's own MAVLink IDs (companion computer), sent as the message source.
    source_system: int = Field(default=1, ge=0, le=255)
    source_component: int = Field(default=1, ge=0, le=255)
    #: Opt-in per the charter carve-out: LANDING_TARGET is advisory and OFF by default.
    enable_landing_target: bool = False
    #: Comma-separated detection class names that trigger a LANDING_TARGET; empty = any.
    target_classes: str = ""
    #: Camera field of view used to convert a bbox centre into MAVLink angular offsets.
    fov_x_rad: float = Field(default=1.204, gt=0.0)  # ~69 deg horizontal
    fov_y_rad: float = Field(default=0.733, gt=0.0)  # ~42 deg vertical

    @property
    def target_class_set(self) -> frozenset[str] | None:
        """Parsed :attr:`target_classes` (``None`` => publish the best of any class)."""
        names = frozenset(c.strip() for c in self.target_classes.split(",") if c.strip())
        return names or None


class PipelineSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PIPELINE_", env_file=_ENV_FILE, extra="ignore")

    #: Idle back-off between empty camera reads (s); non-zero to avoid a 100% CPU spin.
    idle_poll_s: float = Field(default=0.01, ge=0.0)
    #: Stop after this many *consecutive* empty reads; ``None``/unset = run until shutdown
    #: (tolerate transient camera timeouts indefinitely, the live default).
    max_consecutive_empty: int | None = Field(default=None, ge=1)
    #: A frame must be read within this many seconds for the pipeline to report "live"
    #: (liveness != fps, which only ticks on successful frames).
    liveness_timeout_s: float = Field(default=2.0, gt=0.0)
    #: Log a dropped-frame warning on the 1st drop and every Nth thereafter, so a
    #: persistent fault never floods the log at frame rate.
    drop_log_every: int = Field(default=100, ge=1)


class Settings(BaseSettings):
    """Top-level settings composing every domain (each reads its own env prefix)."""

    model_config = SettingsConfigDict(env_prefix="APP_", env_file=_ENV_FILE, extra="ignore")

    log_level: str = "INFO"
    json_logs: bool = False
    yolo: YoloSettings = Field(default_factory=YoloSettings)
    camera: CameraSettings = Field(default_factory=CameraSettings)
    stream: StreamSettings = Field(default_factory=StreamSettings)
    mavlink: MavlinkSettings = Field(default_factory=MavlinkSettings)
    pipeline: PipelineSettings = Field(default_factory=PipelineSettings)


def get_settings() -> Settings:
    """Build a fresh :class:`Settings` from the environment / ``.env``."""
    return Settings()
