"""Synchronized flight logger: RC + telemetry + events per session (§5.4).

One **writer thread** owns all file handles (the only thread in the subsystem;
spec §3). ``record_rc``/``record_telemetry`` are non-blocking enqueues that
**drop-and-count** on overflow (``dropped_records`` per stream, reported at close
and in the manifest). ``record_event`` is durable: it blocks the caller up to
``logger_event_timeout_s`` and raises :class:`LoggerOverflowError` on failure —
events are never silently lost. Because it can block, ``record_event`` must be
called from a sync/tool context or an executor, **never directly on the asyncio
loop thread** (advisory alerts use the non-blocking :class:`ConsoleAlertSink`).

``time.monotonic`` is the only intra-session timebase; the wall clock appears
once, in the manifest. JSONL is chosen over a binary container precisely because
a truncated final line is recoverable after a crash. ``close()`` is idempotent,
drains the queue, and joins the writer thread.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
import uuid
from collections.abc import Sequence
from dataclasses import asdict
from datetime import datetime, timezone
from typing import IO, Any

import structlog

from ..protocols import Clock
from .config import LoggerSettings
from .crsf.telemetry import TelemetryMessage
from .errors import LoggerOverflowError
from .protocols import MonotonicClock
from .version import DATASET_SCHEMA

_log = structlog.get_logger("meshsa.fpv.logger")

#: Queue marker that tells the writer thread to drain and stop.
_SENTINEL: Any = object()
#: Sentinel distinguishing "auto-detect git SHA" from an explicit (incl. None) value.
_AUTO: Any = object()

#: Per-file header field declarations (first line of each JSONL; §5.4.1).
_HEADERS: dict[str, list[str]] = {
    "rc": ["t", "ch"],
    "telemetry": ["t", "type", "data"],
    "events": ["t", "event", "data"],
    "frames": ["t", "frame_idx"],
}


def _read_git_sha() -> str | None:  # pragma: no cover - environment dependent
    """Best-effort ``git rev-parse HEAD``; ``None`` if unavailable."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


class FlightLogger:
    """Writer-thread-backed session logger with a versioned dataset contract."""

    def __init__(
        self,
        settings: LoggerSettings,
        *,
        clock: Clock | None = None,
        settings_snapshot: dict[str, Any] | None = None,
        package_version: str | None = None,
        git_sha: Any = _AUTO,
        capture_latency_ms: float | None = None,
        hardware_notes: str | None = None,
        now_utc: str | None = None,
        session_id: str | None = None,
    ) -> None:
        self._s = settings
        self._clock: Clock = clock or MonotonicClock()
        self._settings_snapshot = settings_snapshot or {}
        self._package_version = package_version
        self._git_sha = _read_git_sha() if git_sha is _AUTO else git_sha
        self._capture_latency_ms = capture_latency_ms
        self._hardware_notes = hardware_notes
        self._created_utc = now_utc or datetime.now(timezone.utc).isoformat()
        self._session_id = session_id or uuid.uuid4().hex[:8]

        self._queue: queue.Queue[Any] = queue.Queue(maxsize=settings.logger_queue_len)
        self._files: dict[str, IO[str]] = {}
        self._thread: threading.Thread | None = None
        self._closed = False
        self._started = False
        self.session_dir = ""

        #: Free-form provenance merged into the manifest at close (e.g. the
        #: link's ``echoes_suppressed`` / ``crc_errors`` counters).
        self._notes: dict[str, Any] = {}
        #: Records dropped per lossy stream (overflow); surfaced in the manifest.
        self.dropped_records: dict[str, int] = {"rc": 0, "telemetry": 0}
        #: Per-telemetry-type observed counts + monotonic time span (rate at close).
        self._tel_counts: dict[str, int] = {}
        self._tel_t_first: float | None = None
        self._tel_t_last: float | None = None

    # -- lifecycle ---------------------------------------------------------- #

    def __enter__(self) -> FlightLogger:
        self.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def start(self) -> None:
        """Create the session directory, write headers, start the writer thread."""
        if self._started:  # pragma: no cover - guarded by callers/tests
            return
        dir_name = f"{self._created_utc.replace(':', '-')}-{self._session_id}"
        self.session_dir = os.path.join(self._s.sessions_root, dir_name)
        os.makedirs(self.session_dir, exist_ok=True)
        for stream, fname in (
            ("rc", "rc.jsonl"),
            ("telemetry", "telemetry.jsonl"),
            ("events", "events.jsonl"),
            ("frames", "frames.jsonl"),
        ):
            # Handle is owned by the writer thread for the session's lifetime and
            # closed in close(); a context manager does not fit this ownership.
            fh = open(os.path.join(self.session_dir, fname), "w", encoding="utf-8")  # noqa: SIM115
            header = {"schema_version": DATASET_SCHEMA, "file": stream, "fields": _HEADERS[stream]}
            fh.write(json.dumps(header) + "\n")
            fh.flush()
            self._files[stream] = fh
        self._write_manifest()
        self._started = True
        self._thread = threading.Thread(target=self._writer, name="fpv-logger", daemon=True)
        self._thread.start()
        _log.debug("flight logger started", session_dir=self.session_dir)

    def close(self) -> None:
        """Drain the queue, stop the writer, finalize the manifest (idempotent).

        Shutdown is bounded by ``logger_shutdown_timeout_s`` on both the sentinel
        enqueue and the thread join, so a wedged writer can never hang the caller
        indefinitely. The writer itself is crash-resilient (a failed record is
        logged and dropped, never fatal), so under normal operation it always
        drains to the sentinel and exits cleanly.
        """
        if self._closed or not self._started:
            return
        # Never join ourselves from inside the writer thread (deadlock guard).
        if threading.current_thread() is self._thread:  # pragma: no cover - defensive
            return
        self._closed = True
        assert self._thread is not None  # always set by start()
        timeout = self._s.logger_shutdown_timeout_s
        try:
            self._queue.put(_SENTINEL, timeout=timeout)
        except queue.Full:  # pragma: no cover - writer wedged (e.g. stuck disk)
            _log.warning("logger queue full; could not enqueue shutdown sentinel")
        self._thread.join(timeout=timeout)
        if self._thread.is_alive():  # pragma: no cover - writer wedged (e.g. stuck disk)
            _log.warning("logger writer thread did not terminate within timeout")
        for fh in self._files.values():
            fh.close()
        self._write_manifest()  # rewrite with final drop counts + telemetry rates
        _log.debug(
            "flight logger closed", session_dir=self.session_dir, dropped=self.dropped_records
        )

    # -- record API --------------------------------------------------------- #

    def record_rc(self, channels: Sequence[int], t: float | None = None) -> None:
        """Enqueue an RC frame record (non-blocking; drops-and-counts on overflow)."""
        self._enqueue_lossy("rc", {"t": self._t(t), "ch": list(channels)})

    def record_telemetry(self, msg: TelemetryMessage, t: float | None = None) -> None:
        """Enqueue a parsed telemetry record (non-blocking; drops-and-counts)."""
        ts = self._t(t)
        name = type(msg).__name__
        self._tel_counts[name] = self._tel_counts.get(name, 0) + 1
        if self._tel_t_first is None:
            self._tel_t_first = ts
        self._tel_t_last = ts
        self._enqueue_lossy("telemetry", {"t": ts, "type": name, "data": asdict(msg)})

    def record_event(
        self, event: str, data: dict[str, Any] | None = None, t: float | None = None
    ) -> None:
        """Enqueue a durable event; blocks up to the timeout, then raises.

        MUST NOT be called on the asyncio loop thread (it can block). Events are
        never silently dropped.
        """
        rec = {"t": self._t(t), "event": event, "data": data or {}}
        try:
            self._queue.put(("events", rec), timeout=self._s.logger_event_timeout_s)
        except queue.Full as exc:
            raise LoggerOverflowError(
                f"event stream blocked > {self._s.logger_event_timeout_s}s: {event!r}"
            ) from exc

    def set_note(self, key: str, value: Any) -> None:
        """Attach a provenance value (e.g. link counters) to the final manifest."""
        self._notes[key] = value

    def record_frame(self, frame_idx: int, t: float | None = None) -> None:
        """Enqueue a video-frame index record (camera arrives in Phase 2).

        The ``frames.jsonl`` contract ships now so the Phase 2 camera wiring needs
        no schema bump; ``t`` is capture-read time (see the manifest's
        ``capture_latency_ms`` for the alignment offset).
        """
        self._enqueue_lossy("frames", {"t": self._t(t), "frame_idx": frame_idx})

    # -- internals ---------------------------------------------------------- #

    def _t(self, t: float | None) -> float:
        return self._clock.now() if t is None else t

    def _enqueue_lossy(self, stream: str, rec: dict[str, Any]) -> None:
        try:
            self._queue.put_nowait((stream, rec))
        except queue.Full:
            self.dropped_records[stream] = self.dropped_records.get(stream, 0) + 1
            _log.warning(
                "logger queue full; dropping record",
                stream=stream,
                dropped=self.dropped_records[stream],
            )

    def _writer(self) -> None:
        last_flush = time.monotonic()
        while True:
            try:
                item = self._queue.get(timeout=self._s.flush_every_s)
            except queue.Empty:
                self._flush()
                last_flush = time.monotonic()
                continue
            if item is _SENTINEL:
                self._queue.task_done()
                break
            stream, rec = item
            try:
                self._files[stream].write(json.dumps(rec) + "\n")
            except (OSError, TypeError, ValueError):
                # A disk error or an unserialisable record must never kill the
                # writer thread — that would wedge close(). Log, count it as a
                # drop, and keep draining so shutdown stays bounded.
                self.dropped_records[stream] = self.dropped_records.get(stream, 0) + 1
                _log.exception("logger write failed; dropping record", stream=stream)
            finally:
                self._queue.task_done()
            if time.monotonic() - last_flush >= self._s.flush_every_s:
                self._flush()
                last_flush = time.monotonic()
        self._flush()

    def _flush(self) -> None:
        for fh in self._files.values():
            fh.flush()

    def _telemetry_rates(self) -> dict[str, float]:
        if self._tel_t_first is None or self._tel_t_last is None:
            return {}
        span = self._tel_t_last - self._tel_t_first
        if span <= 0:
            return {name: float(count) for name, count in self._tel_counts.items()}
        return {name: count / span for name, count in self._tel_counts.items()}

    def _write_manifest(self) -> None:
        manifest = {
            "schema_version": DATASET_SCHEMA,
            "created_utc": self._created_utc,
            "session_id": self._session_id,
            "package_version": self._package_version,
            "git_sha": self._git_sha,
            "capture_latency_ms": self._capture_latency_ms,
            "wiring": self._s.wiring,
            "hardware_notes": self._hardware_notes,
            "settings_snapshot": self._settings_snapshot,
            "telemetry_rates_hz": self._telemetry_rates(),
            "dropped_records": dict(self.dropped_records),
            "notes": dict(self._notes),
            "video": None,  # Phase 2 camera stub; keeps the contract stable
            "files": {
                "rc": "rc.jsonl",
                "telemetry": "telemetry.jsonl",
                "events": "events.jsonl",
                "frames": "frames.jsonl",
                "video": "video.mp4",
            },
        }
        path = os.path.join(self.session_dir, "manifest.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=2, sort_keys=True)
