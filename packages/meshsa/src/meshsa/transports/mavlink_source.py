"""MAVLink telemetry source transport (real pymavlink API).

A receive-only transport that ingests autopilot telemetry from a MAVLink endpoint
(typically a proxy's UDP output such as ``udpin:127.0.0.1:14550``, or a serial
link) and turns each position fix into a structured telemetry frame for the
``telemetry`` codec. Paired with a ``cot`` codec on a TAK leg, a drone shows up as
an ATAK track with no core changes.

Design (matches the framework's seams):
  * The **stateful** MAVLink parse lives here, in a dedicated reader thread, because
    pymavlink is stream/poll-oriented; the ``telemetry`` codec stays a pure per-frame
    map. Parsed fixes cross into the asyncio loop via ``call_soon_threadsafe`` onto
    the shared drop-counting ``_ingest_nowait`` — the same threading pattern as
    :mod:`meshsa.transports.meshtastic_radio`.
  * The pymavlink connection is **injected** (``connection`` / ``connection_factory``)
    so the logic is tested with a fake; only the real link builder is
    ``# pragma: no cover``.
  * Nothing is hard-coded: endpoint, message type, identity, recv timeout and the
    clock are all parameters/config options.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from typing import Any

import structlog

from ..protocols import Clock, SystemClock
from ..registry import transport_registry
from .base import AbstractTransport

_log = structlog.get_logger("meshsa.mavlink")

ConnectionFactory = Callable[[], Any]


def _default_connection_factory(options: dict[str, Any]) -> ConnectionFactory:  # pragma: no cover
    def factory() -> Any:
        from pymavlink import mavutil

        endpoint = options.get("endpoint", "udpin:127.0.0.1:14550")
        return mavutil.mavlink_connection(endpoint)

    return factory


class MavlinkSourceTransport(AbstractTransport):
    def __init__(
        self,
        name: str = "mavlink",
        *,
        connection: Any | None = None,
        connection_factory: ConnectionFactory | None = None,
        message_type: str = "GLOBAL_POSITION_INT",
        source_uid: str = "mav-1",
        callsign: str | None = None,
        recv_timeout_s: float = 1.0,
        clock: Clock | None = None,
        queue_maxsize: int = 1000,
        **_options: Any,
    ) -> None:
        super().__init__(name, queue_maxsize)
        self._conn = connection
        self._factory = connection_factory or _default_connection_factory(_options)
        self._message_type = message_type
        self._source_uid = source_uid
        self._callsign = callsign or source_uid
        self._recv_timeout = recv_timeout_s
        self._clock = clock or SystemClock()
        self._thread: threading.Thread | None = None
        self._reading = False
        #: Monotonic per-fix sequence, so each emitted frame has a unique msg_id
        #: (the router dedupes by msg_id; reusing one id would collapse all fixes).
        self._seq = 0

    async def start(self) -> None:
        await super().start()
        loop = self._get_loop()
        if self._conn is None:
            self._conn = self._factory()  # pragma: no cover - exercised via injection
        self._reading = True
        self._thread = threading.Thread(
            target=self._reader,
            args=(loop, self._conn),
            name=f"mavlink-{self.name}",
            daemon=True,
        )
        self._thread.start()

    @staticmethod
    def _get_loop() -> Any:
        import asyncio

        return asyncio.get_running_loop()

    def _reader(self, loop: Any, conn: Any) -> None:
        """Blocking read loop (own thread); hands each fix to the asyncio loop."""
        while self._reading:
            try:
                msg = conn.recv_match(
                    type=self._message_type, blocking=True, timeout=self._recv_timeout
                )
            except Exception:
                _log.warning("mavlink recv error; stopping reader", transport=self.name)
                break
            if msg is None:
                continue  # idle/timeout — re-check the running flag
            frame = self._to_frame(msg)
            loop.call_soon_threadsafe(self._ingest_nowait, frame)

    def _to_frame(self, msg: Any) -> bytes:
        """Map a ``GLOBAL_POSITION_INT`` message to a telemetry frame (bytes)."""
        self._seq += 1
        frame = {
            "src": self._source_uid,
            "callsign": self._callsign,
            "msg_id": f"{self._source_uid}:{self._seq}",
            "ts": self._clock.now(),
            "lat": msg.lat / 1e7,  # degE7 -> degrees
            "lon": msg.lon / 1e7,
            "hae": msg.alt / 1000.0,  # mm -> metres
        }
        return json.dumps(frame).encode("utf-8")

    async def send(self, data: bytes) -> None:
        # Receive-only source: nothing to transmit back toward the autopilot.
        return None

    async def stop(self) -> None:
        self._reading = False
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                _log.debug("mavlink close error", transport=self.name)
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        await super().stop()


@transport_registry.register("mavlink_source")
def _make_mavlink_source(name: str = "mavlink", **options: Any) -> MavlinkSourceTransport:
    return MavlinkSourceTransport(name=name, **options)
