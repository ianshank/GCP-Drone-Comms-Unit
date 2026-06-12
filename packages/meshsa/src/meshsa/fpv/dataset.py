"""Dataset (JSONL) reading with schema-compatibility enforcement.

Shared by ``fpv-log-replay`` and ``fpv-log-convert`` so the header/compat
handling lives in exactly one place. Mirrors the meshsa wire-compat policy:
accept any ``schema_version`` in the supported window, warn (don't fail) on an
older-but-readable schema, and raise on anything outside the window.
"""

from __future__ import annotations

import json
from typing import Any

from .errors import IncompatibleDatasetError
from .version import (
    DATASET_SCHEMA,
    MIN_COMPATIBLE_DATASET,
    is_dataset_compatible,
    warn_older_dataset,
)


def read_jsonl(path: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Return ``(header, records)`` from a logger JSONL file.

    Streams the file line-by-line (sessions can be large), so the whole file is
    never materialised as raw text. The first line is the schema-versioned header
    record; the remainder are data records. A truncated/garbled *final* line
    (crash recovery) is dropped — that is the whole reason JSONL is used over a
    binary container — but a corrupt line anywhere earlier re-raises, since that
    signals real damage.
    """
    header: dict[str, Any] | None = None
    records: list[dict[str, Any]] = []
    pending_exc: json.JSONDecodeError | None = None
    saw_any = False
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            saw_any = True
            if pending_exc is not None:
                # An earlier line failed to parse and was NOT the last non-empty
                # line -> real mid-file corruption, surface the original error.
                raise pending_exc
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                pending_exc = exc  # tolerated only if it turns out to be the last
                continue
            if header is None:
                header = obj
            else:
                records.append(obj)
    if header is None:
        if saw_any:  # the only content was an unparseable (torn) line
            raise IncompatibleDatasetError(f"no valid JSON records in dataset file: {path}")
        raise IncompatibleDatasetError(f"empty dataset file: {path}")
    _check_schema(header, path)
    return header, records


def _check_schema(header: dict[str, Any], path: str) -> None:
    schema = header.get("schema_version")
    if schema is None or not is_dataset_compatible(schema):
        raise IncompatibleDatasetError(
            f"{path}: schema_version {schema} outside supported window "
            f"[{MIN_COMPATIBLE_DATASET}, {DATASET_SCHEMA}]"
        )
    if schema < DATASET_SCHEMA:
        warn_older_dataset(schema)
