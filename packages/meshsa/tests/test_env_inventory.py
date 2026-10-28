"""Golden inventory of every environment variable the framework honours (design D-11/D-8).

The lists below are the *contract*: every key a field node can be configured with, pinned
by hand from the parsing sites before they collapsed into ``meshsa._envconfig``. The test
proves two things for each key — that setting it changes the loaded value (so a migration
cannot silently drop a binding) and, where the loader exposes an inventory, that the loader
honours no key outside this list (so a migration cannot silently add one either).

Adding a key here is a documented change (CHANGELOG + the env tables in ``docs/specs``);
removing one is a breaking change for deployed units.
"""

from __future__ import annotations

import enum
import types
import typing
from collections.abc import Callable, Mapping
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import BaseModel

from meshsa._envconfig import env_key
from meshsa.config import (
    NODE_ENV_SCALARS,
    NODE_ENV_SECTIONS,
    MeshConfig,
    NodeConfig,
    RouterConfig,
    ScoutConfig,
    node_env_inventory,
)
from meshsa.fpv.config import FpvSettings
from meshsa.health import HealthConfig
from meshsa.inference.config import NemotronConfig
from meshsa.llm.agent import AgentKnobs, resolve_agent_knobs
from meshsa.llm.server import ServerConfig, resolve_config
from meshsa.models import NodeTier
from meshsa.ui.config import UIConfig
from meshsa.ui.logring import VALID_LEVELS

# ── NodeConfig.from_env ───────────────────────────────────────────────────────

_BASE = {"MESHSA_UID": "n1", "MESHSA_CALLSIGN": "N1"}

NODE_TOP_LEVEL = (
    "MESHSA_CONFIG_JSON",
    "MESHSA_UID",
    "MESHSA_CALLSIGN",
    "MESHSA_TIER",
    "MESHSA_PLI_INTERVAL_S",
    "MESHSA_DEFAULT_STALE_S",
)

#: Section → (env section prefix, model). Every field of every section is bindable as
#: ``MESHSA_<SECTION>_<FIELD>``; the counts below are the pinned field counts.
NODE_SECTIONS: dict[str, tuple[str, type[BaseModel], int]] = {
    "mesh": ("MESH", MeshConfig, 4),
    "router": ("ROUTER", RouterConfig, 2),
    "health": ("HEALTH", HealthConfig, 7),
    "inference": ("INFERENCE", NemotronConfig, 20),
    "scout": ("SCOUT", ScoutConfig, 23),
    "ui": ("UI", UIConfig, 16),
}


def node_env_keys() -> list[str]:
    """The full pinned inventory (78 keys) in a stable order."""
    keys = list(NODE_TOP_LEVEL)
    for env_section, model, _ in NODE_SECTIONS.values():
        keys.extend(f"MESHSA_{env_section}_{name.upper()}" for name in model.model_fields)
    return keys


def test_inventory_size_is_pinned() -> None:
    assert len(node_env_keys()) == 78
    for section, (_, model, count) in NODE_SECTIONS.items():
        assert len(model.model_fields) == count, section


def test_loader_inventory_equals_the_pinned_list_exactly() -> None:
    """Both directions: the loader honours every pinned key and no key outside the pin."""
    assert node_env_inventory() == node_env_keys()
    assert tuple(NODE_ENV_SCALARS) == tuple(
        k.removeprefix("MESHSA_").lower() for k in NODE_TOP_LEVEL[1:]
    )
    assert {s: m for s, (_, m, _) in NODE_SECTIONS.items()} == NODE_ENV_SECTIONS
    assert node_env_inventory("X_") == [k.replace("MESHSA_", "X_", 1) for k in node_env_keys()]


_LITERAL_ALTERNATIVES = {"prometheus": "json", "json": "prometheus", "text": "json"}

#: Fields whose validators need a specific shape (a JSON object, an allow-list that must
#: still contain the default model, a known log level, an enum member).
_SPECIAL_SAMPLES = {
    "guided_json_schema": '{"type": "object"}',
    "models": "nvidia/nemotron-3-ultra-550b-a55b,alpha",
    "log_ring_level": "warning",
    "tier": "base",
}

#: Required constructor fields per model, for validating a candidate sample in isolation.
_REQUIRED: dict[type[BaseModel], dict[str, Any]] = {NodeConfig: {"uid": "u", "callsign": "c"}}


def _float_sample(model: type[BaseModel], name: str, default: float) -> str:
    for candidate in (default + 1.0, default / 2 + 0.01, 0.5):
        if candidate == default:
            continue
        try:
            model.model_validate({**_REQUIRED.get(model, {}), name: candidate})
        except ValueError:
            continue
        return repr(candidate)
    raise AssertionError(f"no valid float sample for {model.__name__}.{name}")


def _sample(model: type[BaseModel], name: str) -> str:
    """A string value for ``name`` that validates *and* differs from the default."""
    if name in _SPECIAL_SAMPLES:
        return _SPECIAL_SAMPLES[name]
    field = model.model_fields[name]
    ann = field.annotation
    default = field.default
    origin = typing.get_origin(ann)
    args = typing.get_args(ann)
    if origin is typing.Literal:
        return _LITERAL_ALTERNATIVES[default]
    if ann is bool:
        return "false" if default is True else "true"
    if ann is int or (origin in (typing.Union, types.UnionType) and int in args):
        return str((default if isinstance(default, int) else 0) + 3)
    if ann is float:
        return _float_sample(model, name, default)
    return (default or "") + "x" if isinstance(default, str) else "sample"


def _loaded(env: Mapping[str, str]) -> NodeConfig:
    return NodeConfig.from_env({**_BASE, **env})


@pytest.mark.parametrize("key", NODE_TOP_LEVEL[1:])
def test_top_level_key_is_honoured(key: str) -> None:
    field = key.removeprefix("MESHSA_").lower()
    sample = _sample(NodeConfig, field)
    assert getattr(_loaded({key: sample}), field) != getattr(_loaded({}), field)


@pytest.mark.parametrize(
    "section, key",
    [
        (section, f"MESHSA_{env_section}_{name.upper()}")
        for section, (env_section, model, _) in NODE_SECTIONS.items()
        for name in model.model_fields
    ],
)
def test_section_key_is_honoured(section: str, key: str) -> None:
    env_section, model, _ = NODE_SECTIONS[section]
    field = key.removeprefix(f"MESHSA_{env_section}_").lower()
    sample = _sample(model, field)
    before = getattr(getattr(_loaded({}), section), field)
    after = getattr(getattr(_loaded({key: sample}), section), field)
    assert after != before, (key, sample)


def test_config_json_blob_is_honoured_then_overridden() -> None:
    blob = '{"uid": "n1", "callsign": "BLOB", "router": {"queue_maxsize": 5}}'
    env = {"MESHSA_CONFIG_JSON": blob}
    cfg = NodeConfig.from_env(env)
    assert cfg.callsign == "BLOB"
    assert cfg.router.queue_maxsize == 5
    cfg = NodeConfig.from_env(
        {**env, "MESHSA_CALLSIGN": "SCALAR", "MESHSA_ROUTER_QUEUE_MAXSIZE": "7"}
    )
    assert cfg.callsign == "SCALAR"
    assert cfg.router.queue_maxsize == 7


def test_prefix_is_applied_to_every_key() -> None:
    env = {k.replace("MESHSA_", "X_", 1): v for k, v in _BASE.items()}
    env["X_UI_PORT"] = "8111"
    env["X_SCOUT_STATION_PORT"] = "8112"
    cfg = NodeConfig.from_env(env, prefix="X_")
    assert cfg.ui.port == 8111
    assert cfg.scout.station_port == 8112
    assert NodeConfig.from_env({**_BASE, "X_UI_PORT": "8111"}).ui.port == UIConfig().port


def test_empty_ui_and_health_tokens_keep_their_documented_semantics() -> None:
    cfg = _loaded({"MESHSA_UI_TOKEN": "   ", "MESHSA_HEALTH_TOKEN": ""})
    assert cfg.ui.token is None  # UIConfig normalises an empty credential to None
    assert cfg.health.token == ""  # HealthConfig carries it verbatim (``not token`` is falsy)


def test_bad_values_name_the_variable() -> None:
    with pytest.raises(ValueError, match="MESHSA_INFERENCE_MAX_TOKENS: expected an integer"):
        _loaded({"MESHSA_INFERENCE_MAX_TOKENS": "many"})
    with pytest.raises(ValueError, match="MESHSA_SCOUT_ENABLED: expected a boolean"):
        _loaded({"MESHSA_SCOUT_ENABLED": "ture"})
    with pytest.raises(ValueError, match="MESHSA_HEALTH_PORT: expected an integer"):
        _loaded({"MESHSA_HEALTH_PORT": "http"})


# ── ScoutConfig.from_env (standalone CLI) ─────────────────────────────────────


def test_scout_standalone_honours_the_same_keys() -> None:
    env = {
        f"MESHSA_SCOUT_{name.upper()}": _sample(ScoutConfig, name)
        for name in ScoutConfig.model_fields
    }
    standalone = ScoutConfig.from_env(env)
    nested = _loaded(env).scout
    assert standalone == nested
    assert standalone != ScoutConfig()


# ── llm/server.resolve_config ─────────────────────────────────────────────────

LLM_ENV_KEYS = (
    "MESHSA_LLM_HOST",
    "MESHSA_LLM_PORT",
    "MESHSA_LLM_TOKEN",
    "MESHSA_LLM_MAX_PROMPT_CHARS",
    "MESHSA_MAVLINK2REST_URL",
    "MESHSA_DRONE_UID",
    "MESHSA_FTS_TRACKS_URL",
)


def test_llm_server_keys_are_honoured() -> None:
    env = {
        "MESHSA_LLM_HOST": "0.0.0.0",
        "MESHSA_LLM_PORT": "9090",
        "MESHSA_LLM_TOKEN": " tok \n",
        "MESHSA_LLM_MAX_PROMPT_CHARS": "12",
        "MESHSA_MAVLINK2REST_URL": "http://gw:1",
        "MESHSA_DRONE_UID": "uav-9",
        "MESHSA_FTS_TRACKS_URL": "http://fts/t",
    }
    assert set(env) == set(LLM_ENV_KEYS)
    cfg = resolve_config(env)
    assert cfg == ServerConfig(
        host="0.0.0.0",
        port=9090,
        token="tok",
        max_prompt_chars=12,
        mavlink2rest_url="http://gw:1",
        drone_uid="uav-9",
        fts_tracks_url="http://fts/t",
    )
    assert resolve_config({}) == ServerConfig()
    assert resolve_config({"MESHSA_LLM_TOKEN": "  "}).token is None


def test_llm_server_bounds_name_the_variable() -> None:
    with pytest.raises(ValueError, match="MESHSA_LLM_PORT"):
        resolve_config({"MESHSA_LLM_PORT": "70000"})
    with pytest.raises(ValueError, match="MESHSA_LLM_MAX_PROMPT_CHARS"):
        resolve_config({"MESHSA_LLM_MAX_PROMPT_CHARS": "0"})


# ── llm/agent.resolve_agent_knobs ─────────────────────────────────────────────

AGENT_ENV_KEYS = ("MESHSA_LLM_MODEL", "MESHSA_LLM_MAX_TOKENS", "MESHSA_LLM_MAX_ITERATIONS")


def test_agent_knob_keys_are_honoured() -> None:
    assert resolve_agent_knobs({}) == AgentKnobs()
    knobs = resolve_agent_knobs(
        {
            "MESHSA_LLM_MODEL": "claude-custom",
            "MESHSA_LLM_MAX_TOKENS": "1000",
            "MESHSA_LLM_MAX_ITERATIONS": "5",
        }
    )
    assert knobs == AgentKnobs(model="claude-custom", max_tokens=1000, max_iterations=5)
    with pytest.raises(ValueError, match="MESHSA_LLM_MAX_TOKENS: 0 is below the minimum 1"):
        resolve_agent_knobs({"MESHSA_LLM_MAX_TOKENS": "0"})
    with pytest.raises(ValueError, match="MESHSA_LLM_MAX_ITERATIONS: expected an integer"):
        resolve_agent_knobs({"MESHSA_LLM_MAX_ITERATIONS": "lots"})


# ── fpv/config.FpvSettings.from_env ───────────────────────────────────────────

FPV_ENV_KEYS = ("MESHSA_FPV_CONFIG_JSON", "MESHSA_FPV_SESSIONS_ROOT")


def test_fpv_keys_are_honoured() -> None:
    cfg = FpvSettings.from_env(
        {
            "MESHSA_FPV_CONFIG_JSON": '{"crsf": {"crsf_baud": 420000}}',
            "MESHSA_FPV_SESSIONS_ROOT": "/mnt/ssd/sessions",
        }
    )
    assert cfg.crsf.crsf_baud == 420000
    assert cfg.logger.sessions_root == "/mnt/ssd/sessions"
    # An empty SESSIONS_ROOT is "unset", not "the empty path" (pinned pre-existing semantics).
    assert FpvSettings.from_env({"MESHSA_FPV_SESSIONS_ROOT": ""}).logger.sessions_root == "sessions"
    assert FpvSettings.from_env({}) == FpvSettings()


# ── cli.parse_args env defaults ───────────────────────────────────────────────

CLI_ENV_KEYS: dict[str, tuple[str, str, Callable[[Any], Any]]] = {
    # env key → (argparse dest, sample, expected parsed value)
    "MESHSA_PORT": ("port", "/dev/ttyACM9", str),
    "MESHSA_PORTNUM": ("portnum", "257", int),
    "MESHSA_MESH_REGION": ("region", "EU_868", str),
    "MESHSA_FTS_HOST": ("fts_host", "fts.local", str),
    "MESHSA_FTS_PORT": ("fts_port", "8188", int),
    "MESHSA_UID": ("uid", "base-9", str),
    "MESHSA_CALLSIGN": ("callsign", "BASE9", str),
    "MESHSA_LAT": ("lat", "38.5", float),
    "MESHSA_LON": ("lon", "-122.5", float),
    "MESHSA_PLI_INTERVAL_S": ("interval", "7.5", float),
    "MESHSA_COT_STALE_S": ("stale", "99.0", float),
    "MESHSA_TCP_DELIMITER": ("tcp_delimiter", "\\n", str),
    "MESHSA_HEALTHZ_HOST": ("healthz_host", "0.0.0.0", str),
    "MESHSA_HEALTHZ_PORT": ("healthz_port", "8198", int),
    "MESHSA_LOG_LEVEL": ("log_level", "DEBUG", str),
}


@pytest.mark.parametrize("key", sorted(CLI_ENV_KEYS))
def test_cli_env_default_is_honoured(key: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from meshsa.cli import parse_args

    dest, sample, cast = CLI_ENV_KEYS[key]
    for other in CLI_ENV_KEYS:
        monkeypatch.delenv(other, raising=False)
    monkeypatch.delenv("MESHSA_HEALTH", raising=False)
    before = getattr(parse_args([]), dest)
    monkeypatch.setenv(key, sample)
    after = getattr(parse_args([]), dest)
    assert after == cast(sample)
    assert after != before


def test_cli_health_flag_env_is_presence_based(monkeypatch: pytest.MonkeyPatch) -> None:
    from meshsa.cli import parse_args

    monkeypatch.delenv("MESHSA_HEALTH", raising=False)
    assert parse_args([]).health is False
    monkeypatch.setenv("MESHSA_HEALTH", "1")
    assert parse_args([]).health is True
    monkeypatch.setenv("MESHSA_HEALTH", "")
    assert parse_args([]).health is False


# ── property: from_env(to_env(cfg)) == cfg (design D-11) ─────────────────────
#
# ``to_env`` is the inverse the loader implies: one key per bound field, rendered the way an
# operator would write it in a unit file. If the loader ever stops honouring a key, or parses
# it differently from how the model renders it, the round trip breaks.

_text = st.text(alphabet=st.characters(min_codepoint=32, max_codepoint=126), max_size=20)
_token = st.from_regex(r"[A-Za-z0-9._-]{1,24}", fullmatch=True)
_ident = st.from_regex(r"[a-z0-9][a-z0-9/._-]{0,15}", fullmatch=True)
_port = st.integers(min_value=1, max_value=65535)
_pos_float = st.floats(min_value=0.01, max_value=1e4, allow_nan=False, allow_infinity=False)
_unit = st.floats(min_value=0.0, max_value=0.99, allow_nan=False, allow_infinity=False)


def _render(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, enum.Enum):
        return str(value.value)
    if isinstance(value, (tuple, frozenset)):
        return ",".join(sorted(value) if isinstance(value, frozenset) else value)
    if isinstance(value, float):
        return repr(value)
    return str(value)


def to_env(cfg: NodeConfig, prefix: str = "MESHSA_") -> dict[str, str]:
    env = {env_key(prefix, None, name): _render(getattr(cfg, name)) for name in NODE_ENV_SCALARS}
    for section, model in NODE_ENV_SECTIONS.items():
        sub = getattr(cfg, section)
        for field in model.model_fields:
            value = getattr(sub, field)
            if value is not None:
                env[env_key(prefix, section, field)] = _render(value)
    return env


def _node_configs() -> st.SearchStrategy[NodeConfig]:
    mesh = st.builds(
        MeshConfig,
        channel=_text,
        psk=st.one_of(st.none(), _token),
        region=_text,
        freq_khz=st.one_of(st.none(), st.integers(min_value=0, max_value=10**9)),
    )
    router = st.builds(
        RouterConfig,
        dedupe_cache_size=st.integers(min_value=1, max_value=10**6),
        queue_maxsize=st.integers(min_value=0, max_value=10**6),
    )
    health = st.builds(
        HealthConfig,
        enabled=st.booleans(),
        host=_text,
        port=_port,
        token=st.one_of(st.none(), _text),
        metrics_enabled=st.booleans(),
        metrics_path=_text,
        metrics_format=st.sampled_from(["prometheus", "json"]),
    )
    inference = st.builds(
        NemotronConfig,
        enabled=st.booleans(),
        temperature=_unit,
        max_tokens=st.integers(min_value=1, max_value=10**5),
        models=st.lists(_ident, max_size=3).map(
            lambda more: ("nvidia/nemotron-3-ultra-550b-a55b", *more)
        ),
        response_format=st.sampled_from(["text", "json"]),
        insight_prefix=st.from_regex(r"[A-Za-z\[\] ]{1,12}", fullmatch=True),
        min_interval_s=_unit,
        guided_json_schema=st.sampled_from(["", '{"type": "object"}']),
    )
    scout = st.builds(
        ScoutConfig,
        enabled=st.booleans(),
        rtk_enabled=st.booleans(),
        vine_spacing_m=_pos_float,
        forward_overlap=_unit,
        camera_img_w=st.integers(min_value=1, max_value=8192),
        dem_path=st.one_of(st.none(), _text),
        station_token=_text,
        station_port=_port,
    )
    ui = st.builds(
        UIConfig,
        enabled=st.booleans(),
        host=_text,
        port=_port,
        token=st.one_of(st.none(), _token),
        poll_interval_s=_pos_float,
        max_tracks=st.integers(min_value=1, max_value=10**4),
        log_ring_level=st.sampled_from(sorted(VALID_LEVELS)),
        metrics_format=st.sampled_from(["prometheus", "json"]),
        title=_text,
    )
    return st.builds(
        NodeConfig,
        uid=_token,
        callsign=_text,
        tier=st.sampled_from(list(NodeTier)),
        pli_interval_s=_pos_float,
        default_stale_s=_pos_float,
        mesh=mesh,
        router=router,
        health=health,
        inference=inference,
        scout=scout,
        ui=ui,
    )


@settings(max_examples=60)
@given(_node_configs())
def test_from_env_inverts_to_env(cfg: NodeConfig) -> None:
    assert NodeConfig.from_env(to_env(cfg)) == cfg


@settings(max_examples=30)
@given(_node_configs())
def test_from_env_inverts_to_env_under_another_prefix(cfg: NodeConfig) -> None:
    assert NodeConfig.from_env(to_env(cfg, "X_"), prefix="X_") == cfg
