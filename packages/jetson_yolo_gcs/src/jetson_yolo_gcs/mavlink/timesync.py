"""Vehicle-clock alignment for LANDING_TARGET.time_usec (offset holder + device exchange)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: Microseconds per second — the ``LANDING_TARGET.time_usec`` conversion factor. Defined here
#: (the time module) and imported by ``bridge.py`` so the factor lives in exactly one place.
_USEC_PER_SEC = 1_000_000


@dataclass
class TimeSync:
    """Local->vehicle clock offset (microseconds). ``offset_us`` defaults to 0 (no alignment)."""

    offset_us: int = 0

    def to_vehicle_usec(self, local_s: float) -> int:
        """Convert a local timestamp (seconds) to vehicle-clock microseconds."""
        return int(local_s * _USEC_PER_SEC) + self.offset_us

    def exchange(self, connection: Any) -> None:  # pragma: no cover - real TIMESYNC round-trip
        """Perform a MAVLink TIMESYNC round-trip and update ``offset_us`` (device-only)."""
        raise NotImplementedError
