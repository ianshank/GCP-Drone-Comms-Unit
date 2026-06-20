"""Glue tests for flightctl/run_commander.py (config load, bind guard, signing key).

These cover the operator-facing seams that sit between the JSON/env edge and the
fakes-tested ``meshsa.command`` library — previously untested. They need no aiohttp
or pymavlink (those are imported lazily inside the HTTP/link builders), so they run
in the [dev]-only per-PR CI. The aiohttp app wiring is covered in
``test_run_commander_app.py`` behind an importorskip.
"""

from __future__ import annotations

import inspect
import json

import pytest

# run_commander lives in flightctl/, made importable via the pytest `pythonpath`
# option in pyproject.toml (no per-test sys.path mutation -> no cross-test leakage).
import run_commander


def _write_cfg(tmp_path, **over) -> str:
    cfg = {"mavlink_endpoint": "tcp:127.0.0.1:5760", "audit_path": str(tmp_path / "a.jsonl")}
    cfg.update(over)
    p = tmp_path / "cmd.json"
    p.write_text(json.dumps(cfg), encoding="utf-8")
    return str(p)


# ---- load_config -----------------------------------------------------------
def test_load_config_valid_returns_commander_config(tmp_path):
    cfg = run_commander.load_config(_write_cfg(tmp_path, port=8096))
    assert cfg.port == 8096
    assert cfg.mavlink_endpoint == "tcp:127.0.0.1:5760"


def test_load_config_missing_file_is_clean_systemexit(tmp_path):
    with pytest.raises(SystemExit, match="commander config not found"):
        run_commander.load_config(str(tmp_path / "nope.json"))


def test_load_config_bad_json_is_clean_systemexit(tmp_path):
    # pydantic surfaces malformed JSON as a ValidationError (json_invalid), so it maps
    # to the same clean "invalid commander config" SystemExit, not a raw traceback.
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(SystemExit, match="invalid commander config"):
        run_commander.load_config(str(p))


def test_load_config_unreadable_path_is_clean_systemexit(tmp_path):
    # A directory (or other unreadable target) raises OSError in read -> clean SystemExit.
    with pytest.raises(SystemExit, match="cannot read commander config"):
        run_commander.load_config(str(tmp_path))  # a directory, not a file


def test_load_config_missing_required_field_is_clean_systemexit(tmp_path):
    p = tmp_path / "partial.json"
    p.write_text(json.dumps({"mavlink_endpoint": "tcp:x"}), encoding="utf-8")  # no audit_path
    with pytest.raises(SystemExit, match="invalid commander config"):
        run_commander.load_config(str(p))


# ---- validate_bind ---------------------------------------------------------
def test_validate_bind_loopback_ok_without_token():
    run_commander.validate_bind("127.0.0.1", None)  # no raise


def test_validate_bind_exposed_without_token_fails_closed():
    with pytest.raises(SystemExit, match="without MESHSA_CMD_TOKEN"):
        run_commander.validate_bind("0.0.0.0", None)


def test_validate_bind_exposed_with_token_ok():
    run_commander.validate_bind("0.0.0.0", "s3cr3t")  # no raise


# ---- _read_signing_key -----------------------------------------------------
def test_read_signing_key_none_when_unset():
    assert run_commander._read_signing_key(None) is None
    assert run_commander._read_signing_key("") is None


def test_read_signing_key_wrong_size_fails_closed(tmp_path):
    bad = tmp_path / "key.bin"
    bad.write_bytes(b"\x00" * 16)  # not 32 bytes
    with pytest.raises(SystemExit, match="must be 32 bytes"):
        run_commander._read_signing_key(str(bad))


def test_read_signing_key_valid_32_bytes(tmp_path):
    good = tmp_path / "key.bin"
    good.write_bytes(b"\x01" * 32)
    assert run_commander._read_signing_key(str(good)) == b"\x01" * 32


# ---- secret hygiene contract ----------------------------------------------
def test_build_service_does_not_take_the_environment():
    # Regression guard: build_service must not accept the process environment (it
    # only needs the explicitly-passed signing key), so no token/key can leak in.
    params = inspect.signature(run_commander.build_service).parameters
    assert "env" not in params
    assert "signing_key" in params
