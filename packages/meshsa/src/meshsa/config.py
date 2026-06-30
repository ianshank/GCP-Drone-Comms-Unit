"""Configuration models. Every operational value is a field with an explicit,
overridable default — there are no magic numbers buried in the code."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from typing import Any, Literal

from pydantic import BaseModel, Field

from ._parsing import parse_float, parse_int
from .models import NodeTier


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


class TransportConfig(BaseModel):
    name: str
    type: str  # transport registry key
    enabled: bool = True
    options: dict[str, Any] = Field(default_factory=dict)
    codec: str | None = None  # codec registry key; None -> node default codec
    codec_options: dict[str, Any] = Field(default_factory=dict)


class RouterConfig(BaseModel):
    dedupe_cache_size: int = 2048
    queue_maxsize: int = 1000


class MeshConfig(BaseModel):
    channel: str = "default"
    psk: str | None = None
    region: str = "US"
    freq_khz: int | None = None


class NemotronConfig(BaseModel):
    enabled: bool = False
    api_key: str = ""
    base_url: str = "https://integrate.api.nvidia.com/v1"
    model: str = "nvidia/nemotron-3-ultra-550b-a55b"
    system_prompt: str = "You are a tactical AI assistant. Summarize the user's message clearly. Keep it under 100 words."
    temperature: float = 0.6
    max_tokens: int = 512
    timeout_s: float = 30.0
    max_retries: int = 3
    backoff_base: float = Field(default=2.0, ge=1.0)
    backoff_max_s: float = Field(default=30.0, ge=0.0)
    insight_prefix: str = Field(default="[AI Insight]", min_length=1)


class HealthConfig(BaseModel):
    """Opt-in /healthz listener (served by ``meshsa.health``)."""

    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 8088
    metrics_enabled: bool = False
    metrics_path: str = "/metrics"
    metrics_format: Literal["prometheus", "json"] = "prometheus"


class NodeConfig(BaseModel):
    uid: str
    callsign: str
    tier: NodeTier = NodeTier.USER
    pli_interval_s: float = 30.0
    default_stale_s: float = 120.0
    mesh: MeshConfig = Field(default_factory=MeshConfig)
    router: RouterConfig = Field(default_factory=RouterConfig)
    health: HealthConfig = Field(default_factory=HealthConfig)
    transports: list[TransportConfig] = Field(default_factory=list)
    inference: NemotronConfig = Field(default_factory=NemotronConfig)

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
        def _str(_name: str, value: str) -> str:
            return value

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
        }
        for env_key, (field, caster) in inference_scalars.items():
            if env_key in env:
                inference[field] = caster(env_key, env[env_key])
        if inference:
            data["inference"] = inference

        return cls.model_validate(data)
