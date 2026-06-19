"""Append-only command audit log (the §4c durable record).

This is a purpose-built audit sink, not the FPV :class:`~meshsa.fpv.flight_logger.FlightLogger`
(whose flight-session/manifest/video model does not fit a service-lifetime audit).
It keeps the property that matters for commanding: **a recorded event is never
silently dropped.** Each :meth:`record` writes one JSONL line and (by default)
``fsync``s before returning, so a crash loses at most a partial trailing line —
recoverable, exactly the FlightLogger discipline.

``record`` is synchronous and blocks until the bytes are durable; like
``FlightLogger.record_event`` it **must not** run on the asyncio loop thread —
call it from the executor that runs :class:`~meshsa.command.lifecycle.CommandSender`.
A write error propagates (the command fails closed); it is never swallowed.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import IO, Any

from ..protocols import Clock, SystemClock


class JsonlAuditLog:
    """Single-writer (lock-serialised), append-only, fsync-durable JSONL sink."""

    def __init__(self, path: str | Path, *, clock: Clock | None = None, fsync: bool = True) -> None:
        self._path = Path(path)
        self._clock = clock or SystemClock()
        self._fsync = fsync
        self._lock = threading.Lock()
        self._fh: IO[str] | None = None
        self._closed = False

    def start(self) -> None:
        """Open the log for appending, creating the parent directory if needed."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self._path.open("a", encoding="utf-8")

    def record(self, event: str, data: dict[str, Any]) -> None:
        """Append one durable ``{t, event, data}`` line. Blocks until fsync'd.

        Raises ``RuntimeError`` if called before :meth:`start` or after
        :meth:`close` (so a caller never believes a dropped record was written).
        """
        with self._lock:
            if self._closed or self._fh is None:
                raise RuntimeError("JsonlAuditLog is not started or is already closed")
            rec = {"t": self._clock.now(), "event": event, "data": data}
            self._fh.write(json.dumps(rec, separators=(",", ":")) + "\n")
            self._fh.flush()
            if self._fsync:
                os.fsync(self._fh.fileno())

    def close(self) -> None:
        """Close the log (idempotent). Further :meth:`record` calls then raise."""
        with self._lock:
            if self._fh is not None:
                self._fh.close()
                self._fh = None
            self._closed = True
