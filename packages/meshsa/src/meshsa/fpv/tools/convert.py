"""``fpv-log-convert`` — JSONL session -> Parquet (schema_version-aware).

``pyarrow`` is imported **inside** :func:`to_parquet` so importing this module
(and collecting its tests) never requires the ``[fpv]`` extra. Nested record
fields (e.g. a telemetry ``data`` object) are JSON-encoded to a string column so
one Parquet table can hold a whole heterogeneous stream.
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any

import structlog

from ...cli import log_level_num
from ..dataset import read_jsonl

_log = structlog.get_logger("meshsa.fpv.convert")

#: Streams (JSONL basenames) converted for a session.
_STREAMS = ("rc", "telemetry", "events", "frames")


def flatten_record(rec: dict[str, Any]) -> dict[str, Any]:
    """JSON-encode nested (dict/list) values so columns are uniform scalars."""
    return {k: json.dumps(v) if isinstance(v, (dict, list)) else v for k, v in rec.items()}


def to_parquet(records: list[dict[str, Any]], out_path: str) -> int:
    """Write ``records`` to ``out_path`` as Parquet; return the row count."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    rows = [flatten_record(r) for r in records]
    table = pa.Table.from_pylist(rows)
    pq.write_table(table, out_path)  # type: ignore[no-untyped-call]
    return len(rows)


def convert_file(in_path: str, out_path: str) -> int:
    """Convert a single JSONL file to Parquet (schema-compat enforced on read)."""
    _header, records = read_jsonl(in_path)
    return to_parquet(records, out_path)


def convert_session(session_dir: str, out_dir: str | None = None) -> dict[str, int]:
    """Convert every present stream JSONL in a session directory to Parquet."""
    out_dir = out_dir or session_dir
    os.makedirs(out_dir, exist_ok=True)
    counts: dict[str, int] = {}
    for stream in _STREAMS:
        src = os.path.join(session_dir, f"{stream}.jsonl")
        if not os.path.exists(src):
            continue
        dst = os.path.join(out_dir, f"{stream}.parquet")
        counts[stream] = convert_file(src, dst)
    return counts


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="fpv-log-convert")
    p.add_argument("session_dir", help="path to a session directory")
    p.add_argument("--out-dir", default=None, help="output dir (default: in place)")
    p.add_argument("--log-level", default="INFO", help="DEBUG/INFO/WARNING/ERROR")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - entry point
    args = parse_args(argv)
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(log_level_num(args.log_level))
    )
    counts = convert_session(args.session_dir, args.out_dir)
    _log.info("convert complete", rows=counts)
    return 0
