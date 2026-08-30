"""Configuration models. Every operational value is a field with an explicit,
overridable default — there are no magic numbers buried in the code."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from typing import Any

from pydantic import BaseModel, Field

from ._parsing import parse_float, parse_int
from .defaults import (
    DEFAULT_COT_STALE_S,
    DEFAULT_LOOPBACK_HOST,
    DEFAULT_PLI_INTERVAL_S,
    DEFAULT_QUEUE_MAXSIZE,
    PORT_SCOUT_STATION,
)
from .health import HealthConfig as HealthConfig
from .models import NodeTier
from .ui.config import UIConfig


def _parse_bool(name: str, v: str) -> bool:
    """Parse a boolean from an env-var string value.

    Raises ``ValueError`` for unrecognised inputs so typos like ``"ture"``
    are surfaced at startup rather than silently defaulting to ``False``.
    """
    cleaned = v.strip().lower()
    if cleaned in ("true", "1", "yes"):
        return True
    if cleaned in ("false", "0", "no", ""):
        return False
    raise ValueError(f"{name}: expected a boolean, got {v!r}")


def _str(_name: str, value: str) -> str:
    """No-op caster: the env value is already the target type. ``_name`` exists only so
    every caster in a ``scalar_map`` shares the same ``(env_key, raw_value) -> Any``
    signature."""
    return value


class TransportConfig(BaseModel):
    name: str
    type: str  # transport registry key
    enabled: bool = True
    options: dict[str, Any] = Field(default_factory=dict)
    codec: str | None = None  # codec registry key; None -> node default codec
    codec_options: dict[str, Any] = Field(default_factory=dict)


class RouterConfig(BaseModel):
    dedupe_cache_size: int = 2048
    queue_maxsize: int = DEFAULT_QUEUE_MAXSIZE


class MeshConfig(BaseModel):
    channel: str = "default"
    psk: str | None = None
    region: str = "US"
    freq_khz: int | None = None


# Deliberately not a top-of-file import: meshsa.inference (via .service -> ..router)
# imports RouterConfig from this module, so importing meshsa.inference before
# RouterConfig is defined above would be a circular import against a
# partially-initialized module. Placing the shim here, after RouterConfig, breaks it.
from .inference.config import NemotronConfig as NemotronConfig  # noqa: E402


def _apply_scout_env(scout: dict[str, Any], env: Mapping[str, str], prefix: str) -> dict[str, Any]:
    """Apply every ``<prefix>SCOUT_*`` scalar override to ``scout`` in place; return it.

    Shared by :meth:`NodeConfig.from_env` and :meth:`ScoutConfig.from_env` so the two never
    drift on which environment variables the scout section honours (T-1.5: before this
    helper existed, ``meshsa-scout`` built a bare ``ScoutConfig()`` and silently ignored all
    22 of these, including ``SCOUT_STATION_TOKEN``).
    """
    scout_scalars: dict[str, tuple[str, Callable[[str, str], Any]]] = {
        f"{prefix}SCOUT_ENABLED": ("enabled", _parse_bool),
        f"{prefix}SCOUT_RTK_ENABLED": ("rtk_enabled", _parse_bool),
        f"{prefix}SCOUT_VINE_SPACING_M": ("vine_spacing_m", parse_float),
        f"{prefix}SCOUT_ROW_SPACING_M": ("row_spacing_m", parse_float),
        f"{prefix}SCOUT_DEDUP_RADIUS_M": ("dedup_radius_m", parse_float),
        f"{prefix}SCOUT_SYNC_MAX_SKEW_S": ("sync_max_skew_s", parse_float),
        f"{prefix}SCOUT_ATTITUDE_SIGMA_DEG": ("attitude_sigma_deg", parse_float),
        f"{prefix}SCOUT_POS_CEP_M": ("pos_cep_m", parse_float),
        f"{prefix}SCOUT_MARKER_STALE_S": ("marker_stale_s", parse_float),
        f"{prefix}SCOUT_FORWARD_OVERLAP": ("forward_overlap", parse_float),
        f"{prefix}SCOUT_SIDE_OVERLAP": ("side_overlap", parse_float),
        f"{prefix}SCOUT_SURVEY_ALT_AGL_M": ("survey_alt_agl_m", parse_float),
        f"{prefix}SCOUT_SURVEY_CRUISE_SPEED_MS": ("survey_cruise_speed_ms", parse_float),
        f"{prefix}SCOUT_SURVEY_HOVER_SPEED_MS": ("survey_hover_speed_ms", parse_float),
        f"{prefix}SCOUT_CAMERA_IMG_W": ("camera_img_w", parse_int),
        f"{prefix}SCOUT_CAMERA_IMG_H": ("camera_img_h", parse_int),
        f"{prefix}SCOUT_CAMERA_H_FOV_DEG": ("camera_h_fov_deg", parse_float),
        f"{prefix}SCOUT_CAMERA_V_FOV_DEG": ("camera_v_fov_deg", parse_float),
        f"{prefix}SCOUT_DEM_PATH": ("dem_path", _str),
        f"{prefix}SCOUT_STORE_PATH": ("store_path", _str),
        f"{prefix}SCOUT_STATION_HOST": ("station_host", _str),
        f"{prefix}SCOUT_STATION_PORT": ("station_port", parse_int),
        f"{prefix}SCOUT_STATION_TOKEN": ("station_token", _str),
    }
    for env_key, (field, caster) in scout_scalars.items():
        if env_key in env:
            scout[field] = caster(env_key, env[env_key])
    return scout


class ScoutConfig(BaseModel):
    """Vineyard scouting tunables (``meshsa.scout``; spec §5).

    Every operational value is a field with an explicit default — there are no
    magic numbers in the scout pipeline. ``rtk_enabled`` selects the A1 vine-level
    tier (per-vine pins, cm-level ``pos_cep_m``) vs A2 zone-level.
    """

    enabled: bool = False
    rtk_enabled: bool = True
    vine_spacing_m: float = Field(default=2.0, gt=0.0)
    row_spacing_m: float = Field(default=2.4, gt=0.0)
    dedup_radius_m: float = Field(default=1.0, gt=0.0)
    sync_max_skew_s: float = Field(default=0.05, ge=0.0)
    attitude_sigma_deg: float = Field(default=1.0, ge=0.0)
    pos_cep_m: float = Field(default=0.05, ge=0.0)
    marker_stale_s: float = Field(default=86_400.0, gt=0.0)
    forward_overlap: float = Field(default=0.75, ge=0.0, lt=1.0)
    side_overlap: float = Field(default=0.65, ge=0.0, lt=1.0)
    survey_alt_agl_m: float = Field(default=60.0, gt=0.0)
    survey_cruise_speed_ms: float = Field(default=10.0, gt=0.0)
    survey_hover_speed_ms: float = Field(default=5.0, gt=0.0)
    # Camera intrinsics (field-varying; real values come from calibration, Track H1).
    camera_img_w: int = Field(default=1920, gt=0)
    camera_img_h: int = Field(default=1080, gt=0)
    camera_h_fov_deg: float = Field(default=70.0, gt=0.0, lt=180.0)
    camera_v_fov_deg: float = Field(default=42.0, gt=0.0, lt=180.0)
    dem_path: str | None = None
    store_path: str = ":memory:"
    station_host: str = DEFAULT_LOOPBACK_HOST
    station_port: int = PORT_SCOUT_STATION
    station_token: str = ""

    @classmethod
    def from_env(
        cls, environ: Mapping[str, str] | None = None, prefix: str = "MESHSA_"
    ) -> ScoutConfig:
        """Build a standalone ``ScoutConfig`` from environment variables.

        Applies the same ``<prefix>SCOUT_*`` scalar overrides (and the ``"scout"`` section of
        a ``<prefix>CONFIG_JSON`` blob) that :meth:`NodeConfig.from_env` applies when building
        a full node — so a config authored for a node behaves identically when the
        ``meshsa-scout`` CLI runs standalone. Standalone is the point: unlike ``NodeConfig``,
        this does not require a node identity (``uid``/``callsign``).
        """
        env = dict(os.environ if environ is None else environ)
        data: dict[str, Any] = {}
        blob = env.get(f"{prefix}CONFIG_JSON")
        if blob:
            data.update(json.loads(blob))
        scout = _apply_scout_env(dict(data.get("scout", {})), env, prefix)
        return cls.model_validate(scout)


class NodeConfig(BaseModel):
    uid: str
    callsign: str
    tier: NodeTier = NodeTier.USER
    pli_interval_s: float = DEFAULT_PLI_INTERVAL_S
    default_stale_s: float = DEFAULT_COT_STALE_S
    mesh: MeshConfig = Field(default_factory=MeshConfig)
    router: RouterConfig = Field(default_factory=RouterConfig)
    health: HealthConfig = Field(default_factory=HealthConfig)
    transports: list[TransportConfig] = Field(default_factory=list)
    inference: NemotronConfig = Field(default_factory=NemotronConfig)
    scout: ScoutConfig = Field(default_factory=ScoutConfig)
    ui: UIConfig = Field(default_factory=UIConfig)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> NodeConfig:
        return cls.model_validate(dict(data))

    @classmethod
    def from_file(cls, path: str) -> NodeConfig:
        with open(path, encoding="utf-8") as fh:
            return cls.from_mapping(json.load(fh))

    @classmethod
    def from_env(
        cls, environ: Mapping[str, str] | None = None, prefix: str = "MESHSA_"
    ) -> NodeConfig:
        """Build config from environment variables; a ``<prefix>CONFIG_JSON``
        blob is merged first, then individual scalar overrides are applied."""
        env = dict(os.environ if environ is None else environ)
        data: dict[str, Any] = {}
        blob = env.get(f"{prefix}CONFIG_JSON")
        if blob:
            data.update(json.loads(blob))

        # caster takes (field_name, raw_value) so numeric parse errors name the field.
        # (module-level _str above covers the no-op case; _csv_tuple is the one caster
        # this function still needs locally.)
        def _csv_tuple(_name: str, value: str) -> tuple[str, ...]:
            """Parse a comma-separated env value into a tuple of trimmed, non-empty items."""
            return tuple(x.strip() for x in value.split(",") if x.strip())

        scalar_map: dict[str, tuple[str, Callable[[str, str], Any]]] = {
            f"{prefix}UID": ("uid", _str),
            f"{prefix}CALLSIGN": ("callsign", _str),
            f"{prefix}TIER": ("tier", _str),
            f"{prefix}PLI_INTERVAL_S": ("pli_interval_s", parse_float),
            f"{prefix}DEFAULT_STALE_S": ("default_stale_s", parse_float),
        }
        for env_key, (field, caster) in scalar_map.items():
            if env_key in env:
                data[field] = caster(env_key, env[env_key])
        mesh: dict[str, Any] = dict(data.get("mesh", {}))
        for env_key, field in {
            f"{prefix}MESH_CHANNEL": "channel",
            f"{prefix}MESH_PSK": "psk",
            f"{prefix}MESH_REGION": "region",
        }.items():
            if env_key in env:
                mesh[field] = env[env_key]
        if f"{prefix}MESH_FREQ_KHZ" in env:
            key = f"{prefix}MESH_FREQ_KHZ"
            mesh["freq_khz"] = parse_int(key, env[key])
        if mesh:
            data["mesh"] = mesh

        # --- router (RouterConfig) env-var bindings ---
        router: dict[str, Any] = dict(data.get("router", {}))
        router_scalars: dict[str, tuple[str, Callable[[str, str], Any]]] = {
            f"{prefix}ROUTER_DEDUPE_CACHE_SIZE": ("dedupe_cache_size", parse_int),
            f"{prefix}ROUTER_QUEUE_MAXSIZE": ("queue_maxsize", parse_int),
        }
        for env_key, (field, caster) in router_scalars.items():
            if env_key in env:
                router[field] = caster(env_key, env[env_key])
        if router:
            data["router"] = router

        # --- health (HealthConfig) env-var bindings ---
        health: dict[str, Any] = dict(data.get("health", {}))
        health_scalars: dict[str, tuple[str, Callable[[str, str], Any]]] = {
            f"{prefix}HEALTH_ENABLED": ("enabled", _parse_bool),
            f"{prefix}HEALTH_HOST": ("host", _str),
            f"{prefix}HEALTH_PORT": ("port", parse_int),
            f"{prefix}HEALTH_TOKEN": ("token", _str),
            f"{prefix}HEALTH_METRICS_ENABLED": ("metrics_enabled", _parse_bool),
            f"{prefix}HEALTH_METRICS_PATH": ("metrics_path", _str),
            f"{prefix}HEALTH_METRICS_FORMAT": ("metrics_format", _str),
        }
        for env_key, (field, caster) in health_scalars.items():
            if env_key in env:
                health[field] = caster(env_key, env[env_key])
        if health:
            data["health"] = health

        # --- inference (NemotronConfig) env-var bindings ---
        inference: dict[str, Any] = dict(data.get("inference", {}))
        inference_scalars: dict[str, tuple[str, Callable[[str, str], Any]]] = {
            f"{prefix}INFERENCE_ENABLED": ("enabled", _parse_bool),
            f"{prefix}INFERENCE_API_KEY": ("api_key", _str),
            f"{prefix}INFERENCE_BASE_URL": ("base_url", _str),
            f"{prefix}INFERENCE_MODEL": ("model", _str),
            f"{prefix}INFERENCE_SYSTEM_PROMPT": ("system_prompt", _str),
            f"{prefix}INFERENCE_TEMPERATURE": ("temperature", parse_float),
            f"{prefix}INFERENCE_MAX_TOKENS": ("max_tokens", parse_int),
            f"{prefix}INFERENCE_TIMEOUT_S": ("timeout_s", parse_float),
            f"{prefix}INFERENCE_MAX_RETRIES": ("max_retries", parse_int),
            f"{prefix}INFERENCE_BACKOFF_BASE": ("backoff_base", parse_float),
            f"{prefix}INFERENCE_BACKOFF_MAX_S": ("backoff_max_s", parse_float),
            f"{prefix}INFERENCE_INSIGHT_PREFIX": ("insight_prefix", _str),
            f"{prefix}INFERENCE_MIN_INTERVAL_S": ("min_interval_s", parse_float),
            f"{prefix}INFERENCE_MAX_CONCURRENT_REQUESTS": ("max_concurrent_requests", parse_int),
            f"{prefix}INFERENCE_RESPONSE_FORMAT": ("response_format", _str),
            f"{prefix}INFERENCE_GUIDED_JSON_SCHEMA": ("guided_json_schema", _str),
            f"{prefix}INFERENCE_GUIDED_JSON_SUMMARY_FIELD": ("guided_json_summary_field", _str),
            f"{prefix}INFERENCE_MODELS": ("models", _csv_tuple),
            f"{prefix}INFERENCE_OFFLINE_QUEUE_MAX": ("offline_queue_max", parse_int),
            f"{prefix}INFERENCE_MAX_PENDING_TASKS": ("max_pending_tasks", parse_int),
        }
        for env_key, (field, caster) in inference_scalars.items():
            if env_key in env:
                inference[field] = caster(env_key, env[env_key])
        if inference:
            data["inference"] = inference

        # --- scout (ScoutConfig) env-var bindings ---
        # Shared with ScoutConfig.from_env so the standalone meshsa-scout CLI and a full
        # node resolve MESHSA_SCOUT_* identically.
        scout: dict[str, Any] = _apply_scout_env(dict(data.get("scout", {})), env, prefix)
        if scout:
            data["scout"] = scout

        # --- ui (UIConfig) env-var bindings ---
        ui: dict[str, Any] = dict(data.get("ui", {}))
        ui_scalars: dict[str, tuple[str, Callable[[str, str], Any]]] = {
            f"{prefix}UI_ENABLED": ("enabled", _parse_bool),
            f"{prefix}UI_HOST": ("host", _str),
            f"{prefix}UI_PORT": ("port", parse_int),
            f"{prefix}UI_TOKEN": ("token", _str),
            f"{prefix}UI_MAP_STYLE_URL": ("map_style_url", _str),
            f"{prefix}UI_POLL_INTERVAL_S": ("poll_interval_s", parse_float),
            f"{prefix}UI_TRACK_STALE_S": ("track_stale_s", parse_float),
            f"{prefix}UI_DETECTION_STALE_S": ("detection_stale_s", parse_float),
            f"{prefix}UI_MAX_TRACKS": ("max_tracks", parse_int),
            f"{prefix}UI_MAX_DETECTIONS": ("max_detections", parse_int),
            f"{prefix}UI_CHAT_ENABLED": ("chat_enabled", _parse_bool),
            f"{prefix}UI_LOG_RING_ENABLED": ("log_ring_enabled", _parse_bool),
            f"{prefix}UI_LOG_RING_SIZE": ("log_ring_size", parse_int),
            f"{prefix}UI_LOG_RING_LEVEL": ("log_ring_level", _str),
            f"{prefix}UI_METRICS_FORMAT": ("metrics_format", _str),
            f"{prefix}UI_TITLE": ("title", _str),
        }
        for env_key, (field, caster) in ui_scalars.items():
            if env_key in env:
                ui[field] = caster(env_key, env[env_key])
        if ui:
            data["ui"] = ui

        return cls.model_validate(data)
