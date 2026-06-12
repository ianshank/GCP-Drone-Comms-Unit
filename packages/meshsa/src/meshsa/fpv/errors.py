"""Exception hierarchy for the FPV subsystem.

Rooted at :class:`meshsa.errors.MeshSAError` so callers can catch framework and
FPV errors uniformly.
"""

from __future__ import annotations

from ..errors import MeshSAError


class FpvError(MeshSAError):
    """Base class for all FPV-subsystem errors."""


class TelemetryParseError(FpvError):
    """A known CRSF telemetry frame type failed length/format validation.

    Unknown frame types never raise — they return ``None`` and bump a per-type
    counter (see :meth:`meshsa.fpv.crsf.telemetry.TelemetryParser.parse`).
    """


class CrcError(FpvError):
    """A CRSF frame failed CRC verification during deserialization."""


class LoggerOverflowError(FpvError):
    """The flight logger's event stream could not be enqueued before timeout.

    Raised only on the durable ``event`` stream (never on ``rc``/``telemetry``,
    which drop-and-count); events must never be silently lost.
    """


class ArmGuardError(FpvError):
    """Invalid :class:`meshsa.fpv.arm_guard.ArmGuard` configuration or usage."""
