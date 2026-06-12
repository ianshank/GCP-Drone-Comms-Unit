"""fpv-log-convert: JSONL -> Parquet (Parquet path gated on the [fpv] extra)."""

from __future__ import annotations

import os

import pytest
from _fpv_helpers import ManualClock

from meshsa.fpv.config import LoggerSettings
from meshsa.fpv.crsf.telemetry import LinkStatistics
from meshsa.fpv.flight_logger import FlightLogger
from meshsa.fpv.tools.convert import convert_file, convert_session, flatten_record, parse_args


def test_flatten_record_json_encodes_nested_values():
    # Pure helper — no pyarrow needed; nested dict/list become JSON strings.
    flat = flatten_record({"t": 1.0, "type": "X", "data": {"a": 1}, "ch": [1, 2]})
    assert flat["t"] == 1.0
    assert flat["data"] == '{"a": 1}'
    assert flat["ch"] == "[1, 2]"


def test_parse_args():
    args = parse_args(["sessions/x", "--out-dir", "/tmp/out"])
    assert args.session_dir == "sessions/x"
    assert args.out_dir == "/tmp/out"


def _make_session(tmp_path) -> str:
    logger = FlightLogger(
        LoggerSettings(sessions_root=str(tmp_path)),
        clock=ManualClock(),
        git_sha=None,
        now_utc="2026-06-12T00:00:00+00:00",
        session_id="conv",
    )
    logger.start()
    logger.record_rc([1500, 1500, 1000, 2000], t=0.0)
    logger.record_telemetry(LinkStatistics(-60, -60, 100, 8, 0, 0, 100, -60, 100, 8), t=0.0)
    logger.record_event("health_transition", {"to": "OK"}, t=0.0)
    logger.close()
    return logger.session_dir


def test_convert_session_to_parquet(tmp_path):
    pytest.importorskip("pyarrow")
    import pyarrow.parquet as pq

    session = _make_session(tmp_path)
    out = tmp_path / "parquet"
    counts = convert_session(session, str(out))
    # Every stream present (frames has 0 data rows but still converts its header-less body).
    assert counts["rc"] == 1
    assert counts["telemetry"] == 1
    assert counts["events"] == 1
    # The telemetry parquet is readable and carries the JSON-encoded data column.
    table = pq.read_table(os.path.join(str(out), "telemetry.parquet"))
    assert table.num_rows == 1
    assert "data" in table.column_names


def test_convert_file_direct(tmp_path):
    pytest.importorskip("pyarrow")
    session = _make_session(tmp_path)
    out = tmp_path / "rc.parquet"
    rows = convert_file(os.path.join(session, "rc.jsonl"), str(out))
    assert rows == 1
    assert out.exists()


def test_convert_session_skips_absent_streams(tmp_path):
    pytest.importorskip("pyarrow")
    # A directory with only one stream file present.
    import json

    session = tmp_path / "partial"
    session.mkdir()
    (session / "rc.jsonl").write_text(
        json.dumps({"schema_version": 1, "file": "rc", "fields": ["t", "ch"]})
        + "\n"
        + json.dumps({"t": 0.0, "ch": [1500]})
        + "\n"
    )
    counts = convert_session(str(session), str(tmp_path / "out"))
    assert set(counts) == {"rc"}
