"""Tests for meshsa.ui.config + the MESHSA_UI_* env bindings (spec §5.1)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from meshsa.config import NodeConfig
from meshsa.ui.config import DEFAULT_UI_PORT, UIConfig

_BASE_ENV = {"MESHSA_UID": "n1", "MESHSA_CALLSIGN": "N1"}


def test_defaults_open_no_surface() -> None:
    cfg = UIConfig()
    assert cfg.enabled is False
    assert cfg.host == "127.0.0.1"
    assert cfg.port == DEFAULT_UI_PORT
    assert cfg.token is None
    assert cfg.chat_enabled is False
    assert cfg.log_ring_enabled is False
    assert cfg.metrics_format == "json"


def test_none_token_stays_none() -> None:
    assert UIConfig(token=None).token is None


@pytest.mark.parametrize("raw", ["", "   ", "\t\n"])
def test_empty_token_normalises_to_none(raw: str) -> None:
    assert UIConfig(token=raw).token is None


def test_token_whitespace_stripped() -> None:
    assert UIConfig(token="  s3cret\n").token == "s3cret"


@pytest.mark.parametrize(
    "field,value",
    [
        ("poll_interval_s", 0.0),
        ("track_stale_s", -1.0),
        ("detection_stale_s", 0.0),
        ("max_tracks", 0),
        ("max_detections", -5),
        ("log_ring_size", 0),
        ("port", 0),
        ("port", 65536),
    ],
)
def test_bounds_rejected(field: str, value: float) -> None:
    with pytest.raises(ValidationError):
        UIConfig(**{field: value})


def test_metrics_format_literal() -> None:
    with pytest.raises(ValidationError):
        UIConfig(metrics_format="xml")  # type: ignore[arg-type]


def test_node_config_defaults_include_ui() -> None:
    cfg = NodeConfig.from_env(_BASE_ENV)
    assert cfg.ui == UIConfig()


def test_from_env_full_scalar_map() -> None:
    env = dict(_BASE_ENV)
    env.update(
        {
            "MESHSA_UI_ENABLED": "true",
            "MESHSA_UI_HOST": "0.0.0.0",
            "MESHSA_UI_PORT": "8101",
            "MESHSA_UI_TOKEN": "tok",
            "MESHSA_UI_MAP_STYLE_URL": "http://tiles.local/style.json",
            "MESHSA_UI_POLL_INTERVAL_S": "0.5",
            "MESHSA_UI_TRACK_STALE_S": "60",
            "MESHSA_UI_DETECTION_STALE_S": "120",
            "MESHSA_UI_MAX_TRACKS": "7",
            "MESHSA_UI_MAX_DETECTIONS": "9",
            "MESHSA_UI_CHAT_ENABLED": "yes",
            "MESHSA_UI_LOG_RING_ENABLED": "1",
            "MESHSA_UI_LOG_RING_SIZE": "50",
            "MESHSA_UI_LOG_RING_LEVEL": "warning",
            "MESHSA_UI_METRICS_FORMAT": "prometheus",
            "MESHSA_UI_TITLE": "Unit 7",
        }
    )
    ui = NodeConfig.from_env(env).ui
    assert ui.enabled is True
    assert ui.host == "0.0.0.0"
    assert ui.port == 8101
    assert ui.token == "tok"
    assert ui.map_style_url == "http://tiles.local/style.json"
    assert ui.poll_interval_s == 0.5
    assert ui.track_stale_s == 60.0
    assert ui.detection_stale_s == 120.0
    assert ui.max_tracks == 7
    assert ui.max_detections == 9
    assert ui.chat_enabled is True
    assert ui.log_ring_enabled is True
    assert ui.log_ring_size == 50
    assert ui.log_ring_level == "warning"
    assert ui.metrics_format == "prometheus"
    assert ui.title == "Unit 7"


def test_from_env_empty_token_is_none() -> None:
    env = dict(_BASE_ENV)
    env["MESHSA_UI_TOKEN"] = "   "
    assert NodeConfig.from_env(env).ui.token is None


def test_from_env_bad_number_names_the_variable() -> None:
    env = dict(_BASE_ENV)
    env["MESHSA_UI_PORT"] = "not-a-port"
    with pytest.raises(ValueError, match="MESHSA_UI_PORT"):
        NodeConfig.from_env(env)


def test_config_json_blob_merges_ui() -> None:
    env = dict(_BASE_ENV)
    env["MESHSA_CONFIG_JSON"] = '{"ui": {"enabled": true, "port": 8102}}'
    env["MESHSA_UI_PORT"] = "8103"  # scalar override wins over the blob
    ui = NodeConfig.from_env(env).ui
    assert ui.enabled is True
    assert ui.port == 8103
