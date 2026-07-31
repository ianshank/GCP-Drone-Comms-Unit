"""Tests for the ScoutConfig model + MESHSA_SCOUT_* env bindings."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from meshsa.config import NodeConfig, ScoutConfig


def test_defaults() -> None:
    c = ScoutConfig()
    assert c.enabled is False
    assert c.rtk_enabled is True
    assert c.marker_stale_s == 86_400.0  # overrides the 120 s CoT default
    assert c.station_host == "127.0.0.1"


def test_bounds_enforced() -> None:
    with pytest.raises(ValidationError):
        ScoutConfig(vine_spacing_m=0.0)
    with pytest.raises(ValidationError):
        ScoutConfig(side_overlap=1.0)  # must be < 1


def test_from_env_binds_scout_fields() -> None:
    env = {
        "MESHSA_UID": "n1",
        "MESHSA_CALLSIGN": "SCOUT1",
        "MESHSA_SCOUT_ENABLED": "true",
        "MESHSA_SCOUT_RTK_ENABLED": "false",
        "MESHSA_SCOUT_VINE_SPACING_M": "1.5",
        "MESHSA_SCOUT_DEDUP_RADIUS_M": "0.75",
        "MESHSA_SCOUT_MARKER_STALE_S": "3600",
        "MESHSA_SCOUT_DEM_PATH": "/data/napa.tif",
        "MESHSA_SCOUT_STATION_PORT": "9100",
        "MESHSA_SCOUT_STATION_TOKEN": "secret",
    }
    cfg = NodeConfig.from_env(env)
    assert cfg.scout.enabled is True
    assert cfg.scout.rtk_enabled is False
    assert cfg.scout.vine_spacing_m == 1.5
    assert cfg.scout.dedup_radius_m == 0.75
    assert cfg.scout.marker_stale_s == 3600.0
    assert cfg.scout.dem_path == "/data/napa.tif"
    assert cfg.scout.station_port == 9100
    assert cfg.scout.station_token == "secret"


def test_from_env_default_when_unset() -> None:
    cfg = NodeConfig.from_env({"MESHSA_UID": "n1", "MESHSA_CALLSIGN": "c"})
    assert cfg.scout == ScoutConfig()


def test_from_env_bad_bool_raises() -> None:
    with pytest.raises(ValueError):
        NodeConfig.from_env(
            {"MESHSA_UID": "n", "MESHSA_CALLSIGN": "c", "MESHSA_SCOUT_ENABLED": "ture"}
        )


# ── ScoutConfig.from_env (standalone, code-hygiene-modularity T-1.5) ──────────────────────
#
# Regression: the meshsa-scout CLI used to build a bare ScoutConfig(), silently ignoring all
# 22 wired MESHSA_SCOUT_* variables. ScoutConfig.from_env() is the standalone counterpart to
# NodeConfig.from_env(...).scout — same scalar-override map, no node identity required.


def test_scout_config_from_env_requires_no_node_identity() -> None:
    # The whole point of the standalone method: unlike NodeConfig.from_env, it does not
    # need MESHSA_UID/MESHSA_CALLSIGN.
    cfg = ScoutConfig.from_env({"MESHSA_SCOUT_ENABLED": "true"})
    assert cfg.enabled is True


def test_scout_config_from_env_binds_the_same_fields_as_node_config() -> None:
    env = {
        "MESHSA_SCOUT_ENABLED": "true",
        "MESHSA_SCOUT_RTK_ENABLED": "false",
        "MESHSA_SCOUT_VINE_SPACING_M": "1.5",
        "MESHSA_SCOUT_DEDUP_RADIUS_M": "0.75",
        "MESHSA_SCOUT_MARKER_STALE_S": "3600",
        "MESHSA_SCOUT_DEM_PATH": "/data/napa.tif",
        "MESHSA_SCOUT_STORE_PATH": "/data/pins.db",
        "MESHSA_SCOUT_STATION_HOST": "0.0.0.0",
        "MESHSA_SCOUT_STATION_PORT": "9100",
        "MESHSA_SCOUT_STATION_TOKEN": "secret",
    }
    standalone = ScoutConfig.from_env(env)
    via_node = NodeConfig.from_env({**env, "MESHSA_UID": "n1", "MESHSA_CALLSIGN": "SCOUT1"}).scout
    assert standalone == via_node
    assert standalone.store_path == "/data/pins.db"  # previously silently ignored
    assert standalone.station_token == "secret"  # previously silently ignored


def test_scout_config_from_env_default_when_unset() -> None:
    assert ScoutConfig.from_env({}) == ScoutConfig()


def test_scout_config_from_env_reads_config_json_blob() -> None:
    env = {"MESHSA_CONFIG_JSON": json.dumps({"scout": {"vine_spacing_m": 3.0}})}
    assert ScoutConfig.from_env(env).vine_spacing_m == 3.0
