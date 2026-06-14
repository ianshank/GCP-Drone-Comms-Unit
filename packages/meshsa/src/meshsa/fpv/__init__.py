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

from .arm_guard import ArmGuard
from .camera import CaptureWriter, Frame
from .config import (
    ArmGuardSettings,
    CameraSettings,
    CrsfLinkSettings,
    FpvSettings,
    HealthSettings,
    LoggerSettings,
    ParserSettings,
    ProberSettings,
)
from .crsf.frame import CrsfAddress, CrsfFrame, CrsfFrameType
from .crsf.link import AddressProber, CrsfLink, ProbeResult
from .crsf.telemetry import (
    Attitude,
    BatterySensor,
    FlightMode,
    LinkStatistics,
    TelemetryMessage,
    TelemetryParser,
    message_from_record,
)
from .errors import (
    ArmGuardError,
    CrcError,
    FpvError,
    IncompatibleDatasetError,
    LoggerOverflowError,
    TelemetryParseError,
)
from .flight_logger import FlightLogger
from .link_health import (
    ConsoleAlertSink,
    HealthReport,
    HealthState,
    LinkHealthMonitor,
)
from .protocols import AlertSink, CameraSource, CrsfSerial, MonotonicClock, RCLink
from .telemetry_store import TelemetryStore
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
    "CameraSettings",
    # protocols / clocks
    "RCLink",
    "AlertSink",
    "CrsfSerial",
    "CameraSource",
    "MonotonicClock",
    # crsf wire + parsers
    "CrsfAddress",
    "CrsfFrame",
    "CrsfFrameType",
    "CrsfLink",
    "AddressProber",
    "ProbeResult",
    "TelemetryParser",
    "TelemetryMessage",
    "LinkStatistics",
    "BatterySensor",
    "Attitude",
    "FlightMode",
    "message_from_record",
    # store / health
    "TelemetryStore",
    "LinkHealthMonitor",
    "HealthReport",
    "HealthState",
    "ConsoleAlertSink",
    # logger / arm guard
    "FlightLogger",
    "ArmGuard",
    # camera
    "CaptureWriter",
    "Frame",
    # errors
    "FpvError",
    "TelemetryParseError",
    "CrcError",
    "LoggerOverflowError",
    "ArmGuardError",
    "IncompatibleDatasetError",
]
