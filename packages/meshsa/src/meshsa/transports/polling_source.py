"""Shared base for receive-only *flight-source* transports.

``mavlink_source``, ``msp_source`` and ``crsf_source`` are the same shape: poll a
blocking link on a dedicated reader thread and turn each position fix into a
telemetry frame for the ``telemetry`` codec, so a drone/FPV aircraft shows up as
an ATAK track with no core changes. This base owns everything they share — the
reader-thread lifecycle, ``threading.Event``-based shutdown, the guarded resource
close, and the position-frame builder — so each concrete transport supplies only
its link-specific I/O via three small hooks:

  * :meth:`_poll` — one poll iteration, returning the encoded frames it produced
    (possibly none). It builds frames with :meth:`_position_frame`. An exception
    here stops the reader cleanly (the link is gone); per-item errors that should
    *not* stop the reader (e.g. a single malformed packet) are caught inside the
    subclass's own ``_poll`` and logged.
  * :meth:`_on_open` — optional post-construction open step (default no-op).
  * :meth:`_close` — close the resource (default ``resource.close()``); the base
    wraps the call so a raising ``close`` never breaks shutdown.

Nothing operational is hard-coded: identity, clock, the inter-poll wait and the
join timeout are all constructor parameters; the link/connection itself is
injected (or built by an injected ``factory``) so the plumbing is fully testable
with fakes — no radio, no serial port, no autopilot.
"""

from __future__ import annotations

import abc
import asyncio
import json
import threading
from collections.abc import Callable, Iterable
from typing import Any

import structlog

from ..protocols import Clock, SystemClock
from .base import AbstractTransport

_log = structlog.get_logger("meshsa.transport.source")


class PollingSourceTransport(AbstractTransport):
    """Reader-thread plumbing shared by the receive-only flight-source transports."""

    #: Prefix for the reader thread's name (overridden per concrete transport).
    _thread_prefix: str = "source"

    def __init__(
        self,
        name: str,
        *,
        resource: Any | None,
        factory: Callable[[], Any],
        source_uid: str,
        callsign: str | None = None,
        clock: Clock | None = None,
        queue_maxsize: int = 1000,
        poll_wait_s: float = 0.0,
        join_timeout_s: float = 2.0,
        log_every_n: int = 100,
        log_interval_s: float = 30.0,
    ) -> None:
        super().__init__(name, queue_maxsize)
        self._resource = resource
        self._factory = factory
        self._source_uid = source_uid
        self._callsign = callsign or source_uid
        self._clock = clock or SystemClock()
        #: Wait between poll iterations; ``0`` means the poll itself blocks/paces
        #: (e.g. a blocking ``recv`` with a timeout) so no extra sleep is needed.
        self._poll_wait_s = poll_wait_s
        self._join_timeout_s = join_timeout_s
        #: Emit a throttled link-health log line every ``log_every_n`` frames or
        #: at most once per ``log_interval_s`` (whichever comes first), so a busy
        #: link stays quiet and an idle link still reports ``link="down"``.
        self._log_every_n = log_every_n
        self._log_interval_s = log_interval_s
        self._last_log_at: float | None = None
        self._thread: threading.Thread | None = None
        #: Set by ``stop()`` to wake the reader immediately (no shutdown latency).
        self._stop_event = threading.Event()
        #: Monotonic per-fix sequence so each emitted frame has a unique msg_id
        #: (the router dedupes by msg_id; reusing one would collapse all fixes).
        self._seq = 0
        #: Frames ingested from the link over this transport's lifetime.
        self.rx_frames = 0

    async def start(self) -> None:
        await super().start()
        loop = self._get_loop()
        if self._resource is None:
            self._resource = self._factory()  # pragma: no cover - exercised via injection
        self._on_open(self._resource)
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._reader,
            args=(loop, self._resource),
            name=f"{self._thread_prefix}-{self.name}",
            daemon=True,
        )
        self._thread.start()

    @staticmethod
    def _get_loop() -> asyncio.AbstractEventLoop:
        return asyncio.get_running_loop()

    def _reader(self, loop: asyncio.AbstractEventLoop, resource: Any) -> None:
        """Poll loop on its own thread; hands each frame to the asyncio loop."""
        while not self._stop_event.is_set():
            try:
                frames = self._poll(resource)
            except Exception:
                _log.warning("source poll error; stopping reader", transport=self.name)
                break
            produced = False
            for frame in frames:
                produced = True
                self.rx_frames += 1
                loop.call_soon_threadsafe(self._ingest_nowait, frame)
                if self.rx_frames % self._log_every_n == 0 or self._interval_elapsed():
                    self._log_link("up")
            if not produced and self._interval_elapsed():
                self._log_link("down")
            if self._poll_wait_s:
                self._stop_event.wait(self._poll_wait_s)

    def _interval_elapsed(self) -> bool:
        """True if at least ``log_interval_s`` has passed since the last log line.

        The first call seeds the window (returns ``False``) so an interval-based
        line is only emitted after a full ``log_interval_s`` has actually elapsed.
        """
        now = self._clock.now()
        if self._last_log_at is None:
            self._last_log_at = now
            return False
        return (now - self._last_log_at) >= self._log_interval_s

    def _log_link(self, link: str) -> None:
        """Emit one throttled link-health line and reset the interval window."""
        self._last_log_at = self._clock.now()
        _log.info(
            "source rx",
            transport=self.name,
            rx=self.rx_frames,
            dropped_inbox_full=self.dropped_inbox_full,
            link=link,
        )

    def _position_frame(self, lat: float, lon: float, hae: float) -> bytes:
        """Build the telemetry-codec frame shared by every flight source."""
        self._seq += 1
        frame = {
            "src": self._source_uid,
            "callsign": self._callsign,
            "msg_id": f"{self._source_uid}:{self._seq}",
            "ts": self._clock.now(),
            "lat": lat,
            "lon": lon,
            "hae": hae,
        }
        return json.dumps(frame).encode("utf-8")

    async def send(self, data: bytes) -> None:
        # Receive-only source: nothing to transmit back toward the aircraft.
        return None

    async def stop(self) -> None:
        self._stop_event.set()
        if self._resource is not None:
            try:
                self._close(self._resource)
            except Exception:
                _log.debug("source close error", transport=self.name)
        if self._thread is not None:
            self._thread.join(timeout=self._join_timeout_s)
            self._thread = None
        await super().stop()

    # -- subclass hooks ----------------------------------------------------- #

    def _on_open(self, resource: Any) -> None:
        """Optional open step after the resource is built/injected (default no-op)."""

    def _close(self, resource: Any) -> None:
        """Close the resource; the base swallows any error so stop() is best-effort."""
        resource.close()

    @abc.abstractmethod
    def _poll(self, resource: Any) -> Iterable[bytes]:  # pragma: no cover - abstract
        """One poll iteration → the encoded frames it produced (possibly none)."""
        raise NotImplementedError
