"""Ground-side FPV telemetry subsystem: CRSF ingest, link health, flight logger.

A self-contained subpackage that reuses meshsa's DI/Protocol, pydantic-config,
versioning, and structlog conventions. Importing this package must never require
the optional ``[fpv]`` extra (``pyserial``/``pyarrow``): the hardware serial
factory and the Parquet converter import those **lazily, inside functions**, so
``import meshsa.fpv`` succeeds under meshsa's ``[dev]``-only CI.

Leaf modules import only from ``..protocols`` / ``.protocols`` / ``.errors`` /
``.config`` / ``.version`` (never from this package root) to keep the re-export
surface acyclic.
"""

from __future__ import annotations

from .config import (
    ArmGuardSettings,
    CrsfLinkSettings,
    FpvSettings,
    HealthSettings,
    LoggerSettings,
    ParserSettings,
    ProberSettings,
)
from .errors import (
    ArmGuardError,
    CrcError,
    FpvError,
    LoggerOverflowError,
    TelemetryParseError,
)
from .protocols import AlertSink, CrsfSerial, RCLink
from .version import (
    DATASET_SCHEMA,
    MIN_COMPATIBLE_DATASET,
    DatasetCompatibilityWarning,
    is_dataset_compatible,
)

__all__ = [
    # version / dataset contract
    "DATASET_SCHEMA",
    "MIN_COMPATIBLE_DATASET",
    "DatasetCompatibilityWarning",
    "is_dataset_compatible",
    # settings
    "FpvSettings",
    "ParserSettings",
    "HealthSettings",
    "LoggerSettings",
    "ArmGuardSettings",
    "CrsfLinkSettings",
    "ProberSettings",
    # protocols
    "RCLink",
    "AlertSink",
    "CrsfSerial",
    # errors
    "FpvError",
    "TelemetryParseError",
    "CrcError",
    "LoggerOverflowError",
    "ArmGuardError",
]
