"""FpvSettings loading + defaults (meshsa.fpv.config)."""

from __future__ import annotations

import json

from meshsa.fpv.config import FpvSettings


def test_defaults_are_present_and_typed():
    s = FpvSettings()
    assert s.parser.telemetry_voltage_scale == 0.1
    assert s.health.health_lq_warn == 70
    assert s.health.health_lq_critical == 50
    assert s.logger.logger_queue_len == 4096
    assert s.logger.logger_shutdown_timeout_s == 2.0
    assert s.arm_guard.arm_threshold_us == 1500
    # Corrected half-duplex handset baud (peer-review M-echo).
    assert s.crsf.crsf_baud == 400000
    assert s.crsf.crsf_address == 0xEA
    assert s.crsf.crsf_max_frame_len == 64
    assert s.prober.probe_margin == 3.0


def test_sensitivity_floor_is_version_keyed():
    s = FpvSettings()
    # Default ELRS-3.x baseline is populated and version-aware.
    assert s.health.sensitivity_floor(3, 0) == -120
    assert s.health.sensitivity_floor(3, 2) == -112
    # A version with no map entry returns None rather than a wrong floor.
    assert s.health.sensitivity_floor(2, 0) is None
    assert s.health.sensitivity_floor(3, 99) is None


def test_from_mapping_overrides_nested_defaults():
    s = FpvSettings.from_mapping({"health": {"health_lq_warn": 80}})
    assert s.health.health_lq_warn == 80
    # Untouched siblings keep their defaults.
    assert s.health.health_lq_critical == 50
    assert s.parser.telemetry_voltage_scale == 0.1


def test_from_file_roundtrip(tmp_path):
    p = tmp_path / "fpv.json"
    p.write_text(json.dumps({"logger": {"sessions_root": "/data/sessions"}}))
    s = FpvSettings.from_file(str(p))
    assert s.logger.sessions_root == "/data/sessions"


def test_from_env_blob_then_scalar_override():
    env = {
        "MESHSA_FPV_CONFIG_JSON": json.dumps({"crsf": {"crsf_baud": 420000}}),
        "MESHSA_FPV_SESSIONS_ROOT": "/mnt/ssd/sessions",
    }
    s = FpvSettings.from_env(env)
    assert s.crsf.crsf_baud == 420000  # from blob
    assert s.logger.sessions_root == "/mnt/ssd/sessions"  # scalar override


def test_from_env_empty_yields_defaults():
    s = FpvSettings.from_env({})
    assert s.crsf.crsf_baud == 400000
    assert s.logger.sessions_root == "sessions"
