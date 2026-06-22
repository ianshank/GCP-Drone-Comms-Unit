"""Structural interfaces for the FPV subsystem (dependency injection seams).

Mirrors :mod:`meshsa.protocols`: everything the FPV components need from the
outside world (the RC uplink, an alert destination, the raw serial byte pipe) is
a ``@runtime_checkable`` ``Protocol`` so the stack can be assembled with real or
fake implementations without code changes. The :class:`meshsa.protocols.Clock`
seam is reused as-is for every injected timebase — it is **not** redefined here.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from ..protocols import MonotonicClock as MonotonicClock

if TYPE_CHECKING:
    from .camera import Frame
    from .link_health import HealthReport


@runtime_checkable
class RCLink(Protocol):
    """An RC uplink that transmits a frame of channel values (microseconds).

    :class:`meshsa.fpv.arm_guard.ArmGuard` both *wraps* and *satisfies* this
    Protocol (decorator pattern), so any consumer of an ``RCLink`` keeps working
    unchanged when a guard is interposed.
    """

    def send_rc(self, channels: Sequence[int]) -> None:
        """Transmit one RC frame; ``channels`` are per-channel microsecond values."""
        ...


@runtime_checkable
class AlertSink(Protocol):
    """A destination for link-health advisories.

    Implementations MUST be non-blocking (drop-and-count on backpressure); they
    may be invoked from the asyncio consumer that owns the monitor, so a blocking
    sink would stall the whole loop. Durable persistence of health transitions is
    the flight logger's ``record_event`` responsibility, not the sink's.
    """

    def alert(self, report: HealthReport, previous: HealthReport | None) -> None:
        """Notify of the current health ``report`` and the ``previous`` one."""
        ...


@runtime_checkable
class CrsfSerial(Protocol):
    """The raw byte seam under :class:`meshsa.fpv.crsf.link.CrsfLink`.

    ``read`` MUST be non-blocking or timeout-bounded so the asyncio consumer can
    poll it without stalling: return whatever bytes are available (possibly
    empty), never block indefinitely. The default implementation wraps
    ``pyserial`` and is constructed by an injectable factory so unit tests use a
    scripted fake and require no hardware.
    """

    def read(self, size: int) -> bytes:
        """Return up to ``size`` available bytes (possibly empty); never block."""
        ...

    def write(self, data: bytes) -> int:
        """Write ``data`` to the line; return the number of bytes written."""
        ...

    def close(self) -> None:
        """Release the underlying port."""
        ...


@runtime_checkable
class CameraSource(Protocol):
    """A frame source for the FPV capture writer (Phase 2 camera core).

    ``read_frame`` MUST be timeout-bounded and never block indefinitely: return
    the next :class:`meshsa.fpv.camera.Frame` if one is available, or ``None`` on
    a (bounded) timeout so the capture loop can stay responsive to shutdown. The
    default OpenCV backend is constructed by an injectable factory so unit tests
    use a scripted fake and require no camera hardware; a Jetson deployment can
    swap in a v4l2/GStreamer source behind this same Protocol without code change.
    """

    def read_frame(self) -> Frame | None:
        """Return the next frame, or ``None`` on a bounded timeout (never blocks)."""
        ...

    def close(self) -> None:
        """Release the underlying capture device."""
        ...
