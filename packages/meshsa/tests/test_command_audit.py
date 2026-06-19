"""Append-only JSONL command audit sink (fakes-only; real fsync on tmp files)."""

import json

import pytest
from conftest import FakeClock

from meshsa.command import JsonlAuditLog


def test_records_appended_as_jsonl_in_order(tmp_path):
    # Nested path also exercises parent-directory creation in start().
    path = tmp_path / "audit" / "commands.jsonl"
    log = JsonlAuditLog(path, clock=FakeClock())
    log.start()
    log.record("command_attempt", {"name": "rtl"})
    log.record("command_accepted", {"name": "rtl"})
    log.close()

    recs = [json.loads(line) for line in path.read_text().splitlines()]
    assert [r["event"] for r in recs] == ["command_attempt", "command_accepted"]
    assert recs[0]["data"] == {"name": "rtl"}
    assert recs[0]["t"] == 1001.0  # FakeClock first tick


def test_record_before_start_raises(tmp_path):
    log = JsonlAuditLog(tmp_path / "a.jsonl")
    with pytest.raises(RuntimeError):
        log.record("x", {})


def test_record_after_close_raises(tmp_path):
    log = JsonlAuditLog(tmp_path / "a.jsonl")
    log.start()
    log.close()
    with pytest.raises(RuntimeError):
        log.record("x", {})


def test_close_is_idempotent(tmp_path):
    log = JsonlAuditLog(tmp_path / "a.jsonl")
    log.start()
    log.close()
    log.close()  # second close: fh already None -> no error


def test_fsync_disabled_still_writes(tmp_path):
    path = tmp_path / "a.jsonl"
    log = JsonlAuditLog(path, clock=FakeClock(), fsync=False)
    log.start()
    log.record("e", {"k": 1})
    log.close()
    assert json.loads(path.read_text().splitlines()[0])["data"] == {"k": 1}
