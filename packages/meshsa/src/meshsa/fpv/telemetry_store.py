"""Latest-plus-history store for parsed telemetry (§5.2).

Keyed by message *type* (``LinkStatistics``, ``BatterySensor``, …). Pure state:
no I/O, no threads, no clock — the caller supplies the monotonic timestamp on
``update`` and the current time on ``age_s``. Owned by the single asyncio
consumer; the link health monitor reads it.
"""

from __future__ import annotations

from collections import deque
from typing import TypeVar

from .crsf.telemetry import TelemetryMessage

M = TypeVar("M", bound=TelemetryMessage)


class TelemetryStore:
    """Per-type latest value + a bounded history ring."""

    def __init__(self, history_len: int = 512) -> None:
        if history_len < 1:
            raise ValueError("history_len must be >= 1")
        self._history_len = history_len
        self._latest: dict[type, tuple[TelemetryMessage, float]] = {}
        self._history: dict[type, deque[tuple[TelemetryMessage, float]]] = {}

    def update(self, msg: TelemetryMessage, t_mono: float) -> None:
        """Record ``msg`` observed at monotonic time ``t_mono``."""
        key = type(msg)
        self._latest[key] = (msg, t_mono)
        ring = self._history.get(key)
        if ring is None:
            ring = deque(maxlen=self._history_len)
            self._history[key] = ring
        ring.append((msg, t_mono))

    def latest(self, msg_type: type[M]) -> tuple[M, float] | None:
        """Return ``(msg, t_mono)`` for the newest ``msg_type``, or ``None``."""
        entry = self._latest.get(msg_type)
        if entry is None:
            return None
        return entry  # type: ignore[return-value]

    def age_s(self, msg_type: type, now: float) -> float | None:
        """Seconds since the newest ``msg_type`` was stored, or ``None``."""
        entry = self._latest.get(msg_type)
        if entry is None:
            return None
        return now - entry[1]

    def history(self, msg_type: type[M], n: int) -> list[tuple[M, float]]:
        """Return up to the last ``n`` ``msg_type`` entries (oldest first)."""
        ring = self._history.get(msg_type)
        if ring is None or n <= 0:
            return []
        items = list(ring)
        return items[-n:]  # type: ignore[return-value]
