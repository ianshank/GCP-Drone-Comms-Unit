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
        return cls.model_validate(data)
