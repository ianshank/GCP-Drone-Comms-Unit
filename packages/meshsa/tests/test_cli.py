"""meshsa.cli pure helpers (parse_args / build_config / delimiter).

The live orchestration (run/main) is integration glue (# pragma: no cover).
"""

import logging

import structlog

from meshsa.cli import (
    _delimiter_bytes,
    build_config,
    configure_logging,
    log_level_num,
    parse_args,
)


def test_parse_args_defaults(monkeypatch):
    for k in ("MESHSA_PORT", "MESHSA_FTS_PORT", "MESHSA_HEALTH"):
        monkeypatch.delenv(k, raising=False)
    args = parse_args([])
    assert args.port == "/dev/ttyUSB0"
    assert args.fts_port == 8087
    assert args.health is False
    assert args.healthz_port == 8088


def test_env_default_then_flag_wins(monkeypatch):
    monkeypatch.setenv("MESHSA_PORT", "/dev/ttyACM0")
    assert parse_args([]).port == "/dev/ttyACM0"  # env supplies default
    assert parse_args(["--port", "/dev/ttyUSB9"]).port == "/dev/ttyUSB9"  # flag wins


def test_health_flag_enables(monkeypatch):
    monkeypatch.delenv("MESHSA_HEALTH", raising=False)
    assert parse_args(["--health"]).health is True


def test_log_level_flag_and_env(monkeypatch):
    monkeypatch.delenv("MESHSA_LOG_LEVEL", raising=False)
    assert parse_args([]).log_level == "INFO"  # default
    monkeypatch.setenv("MESHSA_LOG_LEVEL", "DEBUG")
    assert parse_args([]).log_level == "DEBUG"  # env supplies default
    assert parse_args(["--log-level", "WARNING"]).log_level == "WARNING"  # flag wins


def test_log_level_num_maps_names():
    assert log_level_num("DEBUG") == logging.DEBUG
    assert log_level_num("info") == logging.INFO  # case-insensitive
    assert log_level_num("ERROR") == logging.ERROR
    assert log_level_num("bogus") == logging.INFO  # unknown -> INFO


def test_configure_logging_applies_level():
    # Shared structlog wiring used by every entry point; configures global state.
    try:
        configure_logging("WARNING")
        assert structlog.is_configured()
        # Unknown level falls back to INFO via log_level_num (no exception).
        configure_logging("bogus")
        assert structlog.is_configured()
    finally:
        structlog.reset_defaults()  # don't leak global config to other tests


def test_delimiter_bytes_escapes():
    assert _delimiter_bytes("") == b""
    assert _delimiter_bytes("\\n") == b"\n"


def test_build_config_maps_transports_health_and_delimiter():
    args = parse_args(["--health", "--region", "EU", "--tcp-delimiter", "\\n", "--stale", "60"])
    cfg = build_config(args)
    assert cfg.tier.value == "base"
    assert cfg.mesh.region == "EU"
    assert cfg.health.enabled is True
    by_name = {t.name: t for t in cfg.transports}
    assert by_name["mesh"].codec == "compact"
    assert by_name["tak"].options["delimiter"] == b"\n"
    assert by_name["tak"].codec_options == {"stale_s": 60.0}
