"""Dataset schema versioning for the FPV flight-logger contract.

This is a **separate** version namespace from :mod:`meshsa.version`. The wire
``schema_version`` carried by an ``Envelope`` and the on-disk dataset format
(``manifest.json`` + ``*.jsonl`` produced by :mod:`meshsa.fpv.flight_logger`)
evolve independently, so a logger format change never perturbs the meshtastic
wire compatibility window and vice-versa.

The compatibility model mirrors :mod:`meshsa.version`: a reader accepts any
``schema_version`` in ``[MIN_COMPATIBLE_DATASET, DATASET_SCHEMA]``. Adding an
optional field with a default is non-breaking (no bump); renaming, removing, or
reinterpreting a field bumps ``DATASET_SCHEMA``.
"""

from __future__ import annotations

import warnings

#: On-disk dataset schema this build writes (manifest + JSONL header records).
DATASET_SCHEMA = 1
#: Oldest dataset schema this build still reads (raise only on breaking changes).
MIN_COMPATIBLE_DATASET = 1
#: Full set of dataset schemas a reader accepts.
SUPPORTED_DATASET_SCHEMAS: frozenset[int] = frozenset(
    range(MIN_COMPATIBLE_DATASET, DATASET_SCHEMA + 1)
)


class DatasetCompatibilityWarning(UserWarning):
    """Signals that a dataset uses an older-but-supported schema.

    A dedicated category (rather than ``DeprecationWarning``) keeps the
    data-format compatibility signal distinct from API-deprecation warnings, so
    tools can filter on exactly one of them.
    """


def is_dataset_compatible(schema_version: int) -> bool:
    """Return True if this build can read a dataset at ``schema_version``."""
    return MIN_COMPATIBLE_DATASET <= schema_version <= DATASET_SCHEMA


def warn_older_dataset(schema_version: int) -> None:
    """Emit a :class:`DatasetCompatibilityWarning` for an older readable schema."""
    warnings.warn(
        f"dataset schema_version {schema_version} is older than the current "
        f"{DATASET_SCHEMA}; reading with backward-compatible adapters",
        DatasetCompatibilityWarning,
        stacklevel=2,
    )
