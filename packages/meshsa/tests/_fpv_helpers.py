"""Shared fakes for FPV tests (no hardware, fully deterministic).

Importable as a plain module because pytest puts the ``tests/`` directory on
``sys.path`` (the same mechanism that loads ``conftest.py``).
"""

from __future__ import annotations

from meshsa.fpv.crsf.frame import CrsfFrame, CrsfFrameType


class ManualClock:
    """A clock whose time only advances when explicitly told."""

    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def now(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


class FakeCrsfSerial:
    """Scripted half-duplex serial seam: ``write`` optionally echoes onto ``read``."""

    def __init__(self, *, echo: bool = True) -> None:
        self._inbound = bytearray()
        self.written: list[bytes] = []
        self.echo = echo
        self.closed = False

    def feed(self, data: bytes) -> None:
        """Queue ``data`` to be returned by future ``read`` calls (a module reply)."""
        self._inbound.extend(data)

    def read(self, size: int) -> bytes:
        chunk = bytes(self._inbound[:size])
        del self._inbound[:size]
        return chunk

    def write(self, data: bytes) -> int:
        self.written.append(bytes(data))
        if self.echo:  # half-duplex: our own bytes appear on the shared wire
            self._inbound.extend(data)
        return len(data)

    def close(self) -> None:
        self.closed = True


def link_statistics_bytes(addr: int = 0xEA, *, uplink_lq: int = 100) -> bytes:
    """A valid LINK_STATISTICS frame on the wire (for prober/link tests)."""
    payload = bytes([60, 60, uplink_lq, 8, 0, 0, 3, 60, 100, 8])
    return CrsfFrame(addr=addr, type=CrsfFrameType.LINK_STATISTICS, payload=payload).to_bytes()
