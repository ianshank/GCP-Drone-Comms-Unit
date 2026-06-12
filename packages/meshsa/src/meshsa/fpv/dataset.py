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
from .version import DATASET_SCHEMA, is_dataset_compatible, warn_older_dataset


def read_jsonl(path: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Return ``(header, records)`` from a logger JSONL file.

    The first line is the schema-versioned header record; the remainder are data
    records. A truncated/garbled *final* line (crash recovery) is dropped — that
    is the whole reason JSONL is used over a binary container — but a corrupt
    line anywhere earlier re-raises, since that signals real damage.
    """
    with open(path, encoding="utf-8") as fh:
        lines = [line.strip() for line in fh if line.strip()]
    if not lines:
        raise IncompatibleDatasetError(f"empty dataset file: {path}")
    objs: list[dict[str, Any]] = []
    for i, line in enumerate(lines):
        try:
            objs.append(json.loads(line))
        except json.JSONDecodeError:
            if i == len(lines) - 1:
                break  # tolerate only a torn final line
            raise
    if not objs:
        # The sole line was torn/corrupt — no header could be read.
        raise IncompatibleDatasetError(f"no valid JSON records in dataset file: {path}")
    header = objs[0]
    _check_schema(header, path)
    return header, objs[1:]


def _check_schema(header: dict[str, Any], path: str) -> None:
    schema = header.get("schema_version")
    if schema is None or not is_dataset_compatible(schema):
        raise IncompatibleDatasetError(
            f"{path}: schema_version {schema} outside supported window [1, {DATASET_SCHEMA}]"
        )
    if schema < DATASET_SCHEMA:
        warn_older_dataset(schema)
