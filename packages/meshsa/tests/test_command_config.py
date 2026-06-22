"""CommanderConfig validation, staging, and projection to CommanderSettings."""

import json

import pytest
from pydantic import ValidationError

from meshsa.command import CommanderConfig, CommanderSettings


def _minimal(**over) -> dict:
    base = {"mavlink_endpoint": "tcp:127.0.0.1:5760", "audit_path": "/tmp/a.jsonl"}
    base.update(over)
    return base


def test_minimal_config_applies_defaults():
    cfg = CommanderConfig.model_validate(_minimal())
    assert cfg.host == "127.0.0.1"
    assert cfg.port == 8095
    assert cfg.target_system == 1 and cfg.target_component == 1
    assert cfg.allowed == frozenset({"set_mode", "rtl"})
    assert cfg.allow_force_disarm is False


def test_required_fields_missing_raise():
    with pytest.raises(ValidationError):
        CommanderConfig.model_validate({"audit_path": "/tmp/a.jsonl"})  # no endpoint
    with pytest.raises(ValidationError):
        CommanderConfig.model_validate({"mavlink_endpoint": "tcp:x"})  # no audit_path


def test_unknown_keys_are_ignored_not_rejected():
    cfg = CommanderConfig.model_validate(_minimal(_comment="legacy", future_flag=True))
    assert cfg.mavlink_endpoint == "tcp:127.0.0.1:5760"


def test_types_are_coerced_not_strict():
    cfg = CommanderConfig.model_validate(_minimal(port="9000", max_attempts="5"))
    assert cfg.port == 9000
    assert cfg.max_attempts == 5


def test_out_of_range_policy_warns_but_does_not_reject():
    # Staging: a node with out-of-range *policy* values still loads (warning) this release.
    cfg = CommanderConfig.model_validate(_minimal(ack_timeout_s=0, max_attempts=0))
    assert cfg.ack_timeout_s == 0  # accepted (not rejected) this release


def test_out_of_range_port_is_hard_rejected():
    # Port is structurally unbindable when out of range -> reject up front, not warn.
    with pytest.raises(ValidationError):
        CommanderConfig.model_validate(_minimal(port=70000))
    with pytest.raises(ValidationError):
        CommanderConfig.model_validate(_minimal(port=0))


def test_to_settings_projects_policy_subset():
    cfg = CommanderConfig.model_validate(
        _minimal(allowed=["set_mode", "arm"], allow_force_disarm=True, ack_timeout_s=3.0)
    )
    settings = cfg.to_settings()
    assert isinstance(settings, CommanderSettings)
    assert settings.allowed == frozenset({"set_mode", "arm"})
    assert settings.allow_force_disarm is True
    assert settings.ack_timeout_s == 3.0


def test_from_file_roundtrip(tmp_path):
    p = tmp_path / "cmd.json"
    p.write_text(json.dumps(_minimal(port=8096)), encoding="utf-8")
    cfg = CommanderConfig.from_file(p)
    assert cfg.port == 8096


def test_from_env():
    # 1. Loading from minimal environment
    env = {
        "MESHSA_COMMANDER_MAVLINK_ENDPOINT": "udp:127.0.0.1:14550",
        "MESHSA_COMMANDER_AUDIT_PATH": "/tmp/audit.jsonl",
    }
    cfg = CommanderConfig.from_env(environ=env)
    assert cfg.mavlink_endpoint == "udp:127.0.0.1:14550"
    assert cfg.audit_path == "/tmp/audit.jsonl"
    assert cfg.port == 8095  # default

    # 2. Loading with config JSON blob
    env_json = {
        "MESHSA_COMMANDER_CONFIG_JSON": json.dumps(
            {
                "mavlink_endpoint": "tcp:1.1.1.1:5000",
                "audit_path": "/tmp/a.jsonl",
                "port": 9000,
                "allowed": ["rtl"],
            }
        )
    }
    cfg_json = CommanderConfig.from_env(environ=env_json)
    assert cfg_json.mavlink_endpoint == "tcp:1.1.1.1:5000"
    assert cfg_json.port == 9000
    assert cfg_json.allowed == frozenset({"rtl"})

    # 3. Individual scalar overrides on top of JSON
    env_overrides = {
        "MESHSA_COMMANDER_CONFIG_JSON": json.dumps(
            {
                "mavlink_endpoint": "tcp:1.1.1.1:5000",
                "audit_path": "/tmp/a.jsonl",
                "port": 9000,
            }
        ),
        "MESHSA_COMMANDER_PORT": "9001",
        "MESHSA_COMMANDER_ALLOW_FORCE_DISARM": "true",
        "MESHSA_COMMANDER_ACK_TIMEOUT_S": "5.5",
        "MESHSA_COMMANDER_MAX_ATTEMPTS": "10",
        "MESHSA_COMMANDER_ARM_REPORT_MAX_AGE_S": "4.0",
        "MESHSA_COMMANDER_ALLOWED": "set_mode,rtl,arm",
    }
    cfg_overrides = CommanderConfig.from_env(environ=env_overrides)
    assert cfg_overrides.port == 9001
    assert cfg_overrides.allow_force_disarm is True
    assert cfg_overrides.ack_timeout_s == 5.5
    assert cfg_overrides.max_attempts == 10
    assert cfg_overrides.arm_report_max_age_s == 4.0
    assert cfg_overrides.allowed == frozenset({"set_mode", "rtl", "arm"})

    # 4. JSON list format for allowed
    env_json_allowed = {
        "MESHSA_COMMANDER_CONFIG_JSON": json.dumps(
            {
                "mavlink_endpoint": "tcp:1.1.1.1:5000",
                "audit_path": "/tmp/a.jsonl",
            }
        ),
        "MESHSA_COMMANDER_ALLOWED": '["set_mode", "rtl"]',
    }
    cfg_json_allowed = CommanderConfig.from_env(environ=env_json_allowed)
    assert cfg_json_allowed.allowed == frozenset({"set_mode", "rtl"})
