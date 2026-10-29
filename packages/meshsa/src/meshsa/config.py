"""Configuration models. Every operational value is a field with an explicit,
overridable default — there are no magic numbers buried in the code."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, Field

from ._envconfig import (
    apply_overrides,
    env_inventory,
    load_sections,
    merge_config_json,
    parse_bool,
)
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

# ``meshsa.command.config`` (frozen while ``c_gate_met`` is false) imports the boolean
# parser under this name; the implementation moved to ``_envconfig`` (T-3.2). Retire the
# alias in T-8.8, when the frozen file migrates.
_parse_bool = parse_bool


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
        data = merge_config_json({}, env, prefix=prefix)
        scout = apply_overrides(
            cls, dict(data.get("scout", {})), env, prefix=prefix, section="scout"
        )
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
        """Build config from environment variables.

        A ``<prefix>CONFIG_JSON`` blob is merged first, then the top-level scalars
        (:data:`NODE_ENV_SCALARS`) and every field of every section in
        :data:`NODE_ENV_SECTIONS` as ``<prefix><SECTION>_<FIELD>`` — keys and casters derived
        from the models by :mod:`meshsa._envconfig`, so a new section field is bindable the
        moment it exists. :func:`node_env_inventory` lists the resulting keys; the golden test
        pins them.
        """
        env = dict(os.environ if environ is None else environ)
        data = merge_config_json({}, env, prefix=prefix)
        apply_overrides(cls, data, env, prefix=prefix, fields=NODE_ENV_SCALARS)
        load_sections(data, env, prefix=prefix, sections=NODE_ENV_SECTIONS)
        return cls.model_validate(data)


#: Top-level ``NodeConfig`` fields bindable as ``<prefix><FIELD>``. ``transports`` and the
#: sections are structured and bind only through ``<prefix>CONFIG_JSON`` / their own prefix.
NODE_ENV_SCALARS: tuple[str, ...] = ("uid", "callsign", "tier", "pli_interval_s", "default_stale_s")

#: Section name → model; every field binds as ``<prefix><SECTION>_<FIELD>``.
NODE_ENV_SECTIONS: dict[str, type[BaseModel]] = {
    "mesh": MeshConfig,
    "router": RouterConfig,
    "health": HealthConfig,
    "inference": NemotronConfig,
    "scout": ScoutConfig,
    "ui": UIConfig,
}


def node_env_inventory(prefix: str = "MESHSA_") -> list[str]:
    """Every environment variable :meth:`NodeConfig.from_env` honours, in a stable order."""
    return env_inventory(prefix, top_level=NODE_ENV_SCALARS, sections=NODE_ENV_SECTIONS)
