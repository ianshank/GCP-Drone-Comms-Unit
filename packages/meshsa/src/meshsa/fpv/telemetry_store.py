"""Latest-value store for parsed telemetry (§5.2).

Keyed by message *type* (``LinkStatistics``, ``BatterySensor``, …). Pure state:
no I/O, no threads, no clock — the caller supplies the monotonic timestamp on
``update``. Owned by the single asyncio consumer; the link health monitor reads
it. The ``age_s``/``history`` accessors and their backing ring were removed in
T-5.1a (code-hygiene-modularity design D-1): they had no production readers.
"""

from __future__ import annotations

from typing import TypeVar

from .crsf.telemetry import TelemetryMessage

M = TypeVar("M", bound=TelemetryMessage)


class TelemetryStore:
    """Per-type latest value."""

    def __init__(self, history_len: int = 512) -> None:
        # ``history_len`` is retained (and still validated) purely for constructor
        # compatibility: the monitor and replay tools thread it through. Whether it
        # is removed or re-wired to a real ring is T-5.4's store_history_len item.
        if history_len < 1:
            raise ValueError("history_len must be >= 1")
        self._history_len = history_len
        self._latest: dict[type, tuple[TelemetryMessage, float]] = {}

    def update(self, msg: TelemetryMessage, t_mono: float) -> None:
        """Record ``msg`` observed at monotonic time ``t_mono``."""
        self._latest[type(msg)] = (msg, t_mono)

    def latest(self, msg_type: type[M]) -> tuple[M, float] | None:
        """Return ``(msg, t_mono)`` for the newest ``msg_type``, or ``None``."""
        entry = self._latest.get(msg_type)
        if entry is None:
            return None
        return entry  # type: ignore[return-value]
