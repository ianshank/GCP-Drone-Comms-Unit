"""Configuration via pydantic-settings v2 (no magic numbers, per-domain prefixes).

Each domain is its own ``BaseSettings`` with an env prefix so operational values are
grouped and overridable from the environment or a ``.env`` file:

* ``YOLO_*``    — detection model + thresholds
* ``CAMERA_*``  — capture source / geometry
* ``STREAM_*``  — GCS video egress
* ``MAVLINK_*`` — LANDING_TARGET publisher (disabled by default)
* ``TRACKER_*`` — multi-object tracker (disabled by default; read-only, advisory)
* ``APP_*``     — top-level (logging)

The :class:`StreamEncoder` / :class:`CameraType` enums live here (core) so both the
config and the ``streaming`` layer import them in one direction (core -> streaming),
avoiding an import cycle.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

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
    #: Fail-closed gate: when enabled (and ``enable_landing_target``), publishing is
    #: suppressed until a *fresh* autopilot HEARTBEAT is received via ``poll_heartbeat``. The
    #: ``endpoint`` must be able to **receive** heartbeats — verify this for your link (a
    #: strictly send-only path suppresses every publish). This is observable, not silent: the
    #: pipeline snapshot exposes ``landing_target_heartbeat_fresh`` (and ``_suppressed``), so a
    #: link that never delivers beats is visible in ``--health-check``/metrics. Opt out with
    #: ``MAVLINK_REQUIRE_HEARTBEAT=false``.
    require_heartbeat: bool = True
    #: Heartbeat freshness window (s). Matches ArduPilot ``LANDING_TARGET_TIMEOUT_MS`` (2 s):
    #: a beat older than this counts as stale and suppresses publishing.
    heartbeat_timeout_s: float = Field(default=2.0, gt=0.0)
    #: Cadence-floor for observability: if the effective publish rate falls below this, the
    #: pipeline counts a cadence violation (the MAVLink guide recommends 10–50 Hz).
    min_publish_rate_hz: float = Field(default=10.0, gt=0.0)
    #: Autopilot IDs whose HEARTBEAT gates publishing (``0`` = wildcard/any). Distinct from
    #: ``source_system``/``source_component`` above, which are *this* unit's own IDs.
    target_system: int = Field(default=1, ge=0, le=255)
    target_component: int = Field(default=1, ge=0, le=255)
    #: Output frame for LANDING_TARGET. "body_frd" (default, backward-compatible) sends angular
    #: offsets about the body; "local_ned" sends a projected N/E/D position (needs a PoseSource
    #: and a fresh vehicle pose — otherwise the send is fail-safe suppressed).
    frame: Literal["body_frd", "local_ned"] = "body_frd"
    #: Gate the TIMESYNC vehicle-clock offset on the capture-time path: when ``True`` **and** a
    #: ``TimeSync`` is wired, ``capture_time_source="capture"`` maps the frame timestamp onto the
    #: vehicle clock; otherwise the raw capture timestamp is used. Off by default (no offset).
    #: The device-side TIMESYNC round-trip that populates the offset is hardware-only (deferred).
    timesync_enabled: bool = False
    #: Source of LANDING_TARGET.time_usec: "publish" (wall clock at send, default) or
    #: "capture" (per-frame capture timestamp + TIMESYNC offset when available).
    capture_time_source: Literal["publish", "capture"] = "publish"

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
    #: Number of consecutive LANDING_TARGET publish failures **tolerated** before the loop
    #: escalates (re-raises on the next, i.e. the ``tolerance + 1``-th consecutive failure). A
    #: transient link blip is counted and logged, not fatal; a persistently broken safety feed
    #: still fails loud so it never *looks* healthy. ``0`` = fail loud on the first failure.
    publish_failure_tolerance: int = Field(default=3, ge=0)


class TrackerSettings(BaseSettings):
    """Multi-object tracker (Norfair) config. Disabled by default; read-only and advisory.

    When enabled, the tracker assigns a stable id to each detection across frames and the
    pipeline surfaces track-continuity counters in its health snapshot. It **never** feeds
    ``LANDING_TARGET`` target selection (the safety write path) — see
    ``docs/specs/initiative-d-perception.md`` (tracking section).
    """

    model_config = SettingsConfigDict(env_prefix="TRACKER_", env_file=_ENV_FILE, extra="ignore")

    #: Master gate. Off => the tracker is never built and behaviour is byte-identical to a
    #: build without tracking (snapshot track counters stay 0).
    enabled: bool = False
    #: Registry key of the tracker backend.
    backend: str = "norfair"
    #: Norfair distance function. The built-in ``"euclidean"`` compares bbox-centre points in
    #: **raw pixel** coordinates (no normalisation).
    distance_function: str = "euclidean"
    #: Max association distance, in **pixels**, for the euclidean distance (Norfair's own
    #: quick-start uses 20). Required by Norfair (it has no upstream default).
    distance_threshold: float = Field(default=20.0, gt=0.0)
    #: Frames a track survives without a match before it is dropped (Norfair default 15).
    hit_counter_max: int = Field(default=15, gt=0)
    #: Frames before a tentative track is confirmed and assigned a stable id.
    initialization_delay: int = Field(default=3, ge=0)


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
    tracker: TrackerSettings = Field(default_factory=TrackerSettings)


def get_settings() -> Settings:
    """Build a fresh :class:`Settings` from the environment / ``.env``."""
    return Settings()
