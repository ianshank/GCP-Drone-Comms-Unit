"""FlightLogger: session contract, overflow policy, manifest (§5.4)."""

from __future__ import annotations

import json
import os

import pytest
from _fpv_helpers import ManualClock

from meshsa.fpv.config import LoggerSettings
from meshsa.fpv.crsf.telemetry import Attitude, LinkStatistics
from meshsa.fpv.errors import LoggerOverflowError
from meshsa.fpv.flight_logger import FlightLogger
from meshsa.fpv.version import DATASET_SCHEMA


def _ls() -> LinkStatistics:
    return LinkStatistics(-60, -60, 100, 8, 0, 0, 100, -60, 100, 8)


def _read_lines(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _read_json(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.loads(fh.read())


def _logger(tmp_path, **kw) -> FlightLogger:
    settings = LoggerSettings(sessions_root=str(tmp_path), **kw.pop("settings", {}))
    return FlightLogger(
        settings,
        clock=ManualClock(),
        git_sha="deadbeef",
        package_version="0.2.0",
        now_utc="2026-06-12T00:00:00+00:00",
        session_id="testsess",
        settings_snapshot={"crsf": {"crsf_baud": 400000}},
        capture_latency_ms=None,
        **kw,
    )


def test_session_dir_and_headers(tmp_path):
    with _logger(tmp_path) as logger:
        session_dir = logger.session_dir
    assert os.path.isdir(session_dir)
    # Every JSONL's first line is a schema-versioned header naming its fields.
    for fname, stream in (
        ("rc.jsonl", "rc"),
        ("telemetry.jsonl", "telemetry"),
        ("events.jsonl", "events"),
        ("frames.jsonl", "frames"),
    ):
        header = _read_lines(os.path.join(session_dir, fname))[0]
        assert header["schema_version"] == DATASET_SCHEMA
        assert header["file"] == stream
        assert isinstance(header["fields"], list)


def test_records_are_written_with_monotonic_timestamps(tmp_path):
    logger = _logger(tmp_path)
    logger.start()
    logger.record_rc([1500, 1500, 1000, 2000], t=1.0)
    logger.record_telemetry(_ls(), t=1.0)
    logger.record_telemetry(Attitude(0.1, -0.2, 0.0), t=3.0)
    logger.record_event("health_transition", {"to": "WARN"}, t=2.0)
    logger.record_frame(0, t=1.5)
    logger.close()

    rc = _read_lines(os.path.join(logger.session_dir, "rc.jsonl"))
    assert rc[1] == {"t": 1.0, "ch": [1500, 1500, 1000, 2000]}
    tel = _read_lines(os.path.join(logger.session_dir, "telemetry.jsonl"))
    assert tel[1]["type"] == "LinkStatistics"
    assert tel[1]["data"]["uplink_lq"] == 100
    assert tel[2]["type"] == "Attitude"
    events = _read_lines(os.path.join(logger.session_dir, "events.jsonl"))
    assert events[1] == {"t": 2.0, "event": "health_transition", "data": {"to": "WARN"}}
    frames = _read_lines(os.path.join(logger.session_dir, "frames.jsonl"))
    assert frames[1] == {"t": 1.5, "frame_idx": 0}


def test_every_written_line_is_valid_json_recoverable(tmp_path):
    # JSONL guarantees each record is an independently parseable line — a crash
    # can only ever truncate the final one.
    logger = _logger(tmp_path)
    logger.start()
    for i in range(50):
        logger.record_rc([1500] * 4, t=float(i))
    logger.close()
    lines = _read_lines(os.path.join(logger.session_dir, "rc.jsonl"))
    assert len(lines) == 51  # header + 50 records, all valid JSON


def test_manifest_contract(tmp_path):
    logger = _logger(tmp_path)
    logger.start()
    logger.record_telemetry(_ls(), t=0.0)
    logger.record_telemetry(_ls(), t=2.0)  # 2 over 2s -> 1 Hz
    logger.close()
    manifest = _read_json(os.path.join(logger.session_dir, "manifest.json"))
    assert manifest["schema_version"] == DATASET_SCHEMA
    assert manifest["capture_latency_ms"] is None  # null until measured
    assert manifest["wiring"] == "half_duplex_tied"
    assert manifest["git_sha"] == "deadbeef"
    assert manifest["package_version"] == "0.2.0"
    assert manifest["dropped_records"] == {"rc": 0, "telemetry": 0}
    assert manifest["telemetry_rates_hz"]["LinkStatistics"] == pytest.approx(1.0)
    assert manifest["video"] is None  # Phase 2 stub
    assert manifest["settings_snapshot"]["crsf"]["crsf_baud"] == 400000


def test_close_is_idempotent_and_supports_context_manager(tmp_path):
    logger = _logger(tmp_path)
    logger.start()
    logger.record_rc([1500] * 4, t=0.0)
    logger.close()
    logger.close()  # idempotent, no error
    # close() before start() is a no-op.
    _logger(tmp_path).close()


# --------------------------------------------------------------------------- #
# Overflow policy — exercised without the writer thread for determinism.       #
# --------------------------------------------------------------------------- #


def test_rc_and_telemetry_drop_and_count_on_overflow(tmp_path):
    logger = _logger(tmp_path, settings={"logger_queue_len": 1})
    logger._queue.put_nowait(("rc", {}))  # occupy the only slot
    logger.record_rc([1, 2, 3, 4], t=1.0)
    logger.record_telemetry(_ls(), t=1.0)
    assert logger.dropped_records["rc"] == 1
    assert logger.dropped_records["telemetry"] == 1


def test_event_overflow_blocks_then_raises(tmp_path):
    logger = _logger(tmp_path, settings={"logger_queue_len": 1, "logger_event_timeout_s": 0.01})
    logger._queue.put_nowait(("rc", {}))  # fill the queue; no writer draining it
    with pytest.raises(LoggerOverflowError, match="event stream blocked"):
        logger.record_event("must_not_drop", {"k": "v"}, t=1.0)


def test_default_monotonic_clock_used_when_none_injected(tmp_path):
    from meshsa.fpv.protocols import MonotonicClock

    t = MonotonicClock().now()
    assert isinstance(t, float)
    # A logger with no injected clock stamps real monotonic floats.
    logger = FlightLogger(
        LoggerSettings(sessions_root=str(tmp_path)),
        git_sha=None,
        now_utc="2026-06-12T00:00:00+00:00",
        session_id="defclk",
    )
    logger.start()
    logger.record_rc([1500] * 4)  # t=None -> monotonic
    logger.close()
    rc = _read_lines(os.path.join(logger.session_dir, "rc.jsonl"))
    assert isinstance(rc[1]["t"], float)


def test_writer_flush_paths_with_zero_interval(tmp_path):
    # flush_every_s=0 makes both writer timing branches deterministic: the
    # get() times out immediately (Empty -> flush) and every processed record
    # trips the interval flush.
    logger = _logger(tmp_path, settings={"flush_every_s": 0.0})
    logger.start()
    logger.record_rc([1500] * 4, t=1.0)
    logger.record_event("e", {}, t=1.0)
    logger.close()
    assert len(_read_lines(os.path.join(logger.session_dir, "rc.jsonl"))) == 2


def test_zero_span_telemetry_rate_falls_back_to_count(tmp_path):
    logger = _logger(tmp_path)
    logger.start()
    logger.record_telemetry(_ls(), t=5.0)
    logger.record_telemetry(_ls(), t=5.0)  # same instant -> span 0
    logger.close()
    manifest = _read_json(os.path.join(logger.session_dir, "manifest.json"))
    assert manifest["telemetry_rates_hz"]["LinkStatistics"] == 2.0


def test_git_sha_failure_path_yields_none(tmp_path):
    # Explicit git_sha=None models a build with no .git / no git on PATH.
    logger = FlightLogger(
        LoggerSettings(sessions_root=str(tmp_path)),
        clock=ManualClock(),
        git_sha=None,
        now_utc="2026-06-12T00:00:00+00:00",
        session_id="nogit",
    )
    logger.start()
    logger.close()
    manifest = _read_json(os.path.join(logger.session_dir, "manifest.json"))
    assert manifest["git_sha"] is None
