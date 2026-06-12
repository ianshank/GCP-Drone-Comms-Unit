"""Dataset JSONL reader: header, schema-compat window, crash recovery."""

from __future__ import annotations

import json
import warnings

import pytest

from meshsa.fpv.dataset import read_jsonl
from meshsa.fpv.errors import IncompatibleDatasetError
from meshsa.fpv.version import DatasetCompatibilityWarning


def _write(path, lines: list[str]) -> str:
    path.write_text("\n".join(lines) + "\n")
    return str(path)


def test_reads_header_and_records(tmp_path):
    p = _write(
        tmp_path / "telemetry.jsonl",
        [
            json.dumps({"schema_version": 1, "file": "telemetry", "fields": ["t", "type"]}),
            json.dumps({"t": 1.0, "type": "LinkStatistics", "data": {}}),
            json.dumps({"t": 2.0, "type": "Attitude", "data": {}}),
        ],
    )
    header, records = read_jsonl(p)
    assert header["file"] == "telemetry"
    assert [r["t"] for r in records] == [1.0, 2.0]


def test_empty_file_raises(tmp_path):
    p = tmp_path / "empty.jsonl"
    p.write_text("")
    with pytest.raises(IncompatibleDatasetError, match="empty"):
        read_jsonl(str(p))


def test_incompatible_schema_raises(tmp_path):
    p = _write(tmp_path / "f.jsonl", [json.dumps({"schema_version": 999, "file": "rc"})])
    with pytest.raises(IncompatibleDatasetError, match="outside supported window"):
        read_jsonl(p)


def test_missing_schema_version_raises(tmp_path):
    p = _write(tmp_path / "f.jsonl", [json.dumps({"file": "rc"})])
    with pytest.raises(IncompatibleDatasetError):
        read_jsonl(p)


def test_single_torn_line_raises_descriptive_error(tmp_path):
    # The sole line is truncated -> no header readable -> descriptive error, not
    # a raw IndexError on objs[0].
    p = tmp_path / "rc.jsonl"
    p.write_text('{"t": 1.0, "ch": [1')
    with pytest.raises(IncompatibleDatasetError, match="no valid JSON records"):
        read_jsonl(str(p))


def test_torn_final_line_is_tolerated(tmp_path):
    p = tmp_path / "rc.jsonl"
    p.write_text(
        json.dumps({"schema_version": 1, "file": "rc"})
        + "\n"
        + json.dumps({"t": 1.0, "ch": [1]})
        + "\n"
        + '{"t": 2.0, "ch": [1'  # truncated final line (crash)
    )
    header, records = read_jsonl(str(p))
    assert header["file"] == "rc"
    assert [r["t"] for r in records] == [1.0]  # torn line dropped


def test_mid_file_corruption_raises(tmp_path):
    p = tmp_path / "rc.jsonl"
    p.write_text(
        json.dumps({"schema_version": 1, "file": "rc"})
        + "\n"
        + "{ this is not json }\n"
        + json.dumps({"t": 2.0, "ch": [1]})
        + "\n"
    )
    with pytest.raises(json.JSONDecodeError):
        read_jsonl(str(p))


def test_older_but_supported_schema_warns(tmp_path, monkeypatch):
    # Force the window to advertise a newer current schema so 1 is "older".
    monkeypatch.setattr("meshsa.fpv.dataset.DATASET_SCHEMA", 2)
    monkeypatch.setattr("meshsa.fpv.dataset.is_dataset_compatible", lambda v: 1 <= v <= 2)
    p = _write(tmp_path / "f.jsonl", [json.dumps({"schema_version": 1, "file": "rc"})])
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        read_jsonl(p)
    assert any(issubclass(w.category, DatasetCompatibilityWarning) for w in caught)
