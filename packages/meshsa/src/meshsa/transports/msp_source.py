"""Betaflight MSP telemetry source transport (YAMSPy / MultiWii Serial Protocol).

A receive-only transport that polls a Betaflight flight controller over serial for
position (MSP_RAW_GPS) and turns each fix into a telemetry frame for the
``telemetry`` codec — the same seam as :mod:`meshsa.transports.mavlink_source`, so a
drone/FC shows up as an ATAK track with no core changes.

Design:
  * The MSP request/response poll (hardware/YAMSPy specific) is an **injectable**
    ``poll`` callable; its default talks to a real ``yamspy.MSPy`` board and is
    ``# pragma: no cover``. The board itself is injected too (``board`` /
    ``board_factory``). So the transport plumbing — reader thread, framing,
    ingest, lifecycle — is fully tested with fakes; no FC, no serial, no socat.
  * Polling runs on a dedicated thread (MSP is blocking serial I/O); each fix
    crosses into the asyncio loop via ``call_soon_threadsafe`` onto the shared
    drop-counting ``_ingest_nowait``.
  * Nothing is hard-coded: device/baud, poll interval, identity, coordinate/alt
    scaling and the clock are parameters/config options. Coordinate scaling is
    configurable because MSP GPS units vary by firmware (Betaflight reports lat/lon
    in 1e7 degrees; ``coord_scale`` defaults accordingly).
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from typing import Any

import structlog

from ..protocols import Clock, SystemClock
from ..registry import transport_registry
from .base import AbstractTransport

_log = structlog.get_logger("meshsa.msp")

BoardFactory = Callable[[], Any]
#: A board -> position-fix mapper: returns {"lat","lon","alt"} (raw MSP units) or None.
PollFn = Callable[[Any], "dict[str, Any] | None"]


def _default_board_factory(options: dict[str, Any]) -> BoardFactory:  # pragma: no cover
    def factory() -> Any:
        from yamspy import MSPy

        board = MSPy(
            device=options.get("device", "/dev/ttyACM0"),
            loglevel=options.get("loglevel", "WARNING"),
            baudrate=int(options.get("baudrate", 115200)),
        )
        board.connect(trials=board.ser_trials)
        return board

    return factory


def _default_poll(board: Any) -> dict[str, Any] | None:  # pragma: no cover - needs YAMSPy + FC
    from yamspy import MSPy

    if board.send_RAW_msg(MSPy.MSPCodes["MSP_RAW_GPS"], data=[]):
        dataHandler = board.receive_msg()
        board.process_recv_data(dataHandler)
    gps = board.GPS_DATA
    if not gps.get("fix"):
        return None
    return {"lat": gps["lat"], "lon": gps["lon"], "alt": gps.get("alt", 0)}


class MspSourceTransport(AbstractTransport):
    def __init__(
        self,
        name: str = "msp",
        *,
        board: Any | None = None,
        board_factory: BoardFactory | None = None,
        poll: PollFn | None = None,
        source_uid: str = "fc-1",
        callsign: str | None = None,
        coord_scale: float = 1e7,
        alt_scale: float = 1.0,
        poll_interval_s: float = 1.0,
        clock: Clock | None = None,
        queue_maxsize: int = 1000,
        **_options: Any,
    ) -> None:
        super().__init__(name, queue_maxsize)
        self._board = board
        self._factory = board_factory or _default_board_factory(_options)
        self._poll = poll or _default_poll
        self._source_uid = source_uid
        self._callsign = callsign or source_uid
        self._coord_scale = coord_scale
        self._alt_scale = alt_scale
        self._poll_interval = poll_interval_s
        self._clock = clock or SystemClock()
        self._thread: threading.Thread | None = None
        self._reading = False
        self._seq = 0

    async def start(self) -> None:
        await super().start()
        loop = self._get_loop()
        if self._board is None:
            self._board = self._factory()  # pragma: no cover - exercised via injection
        self._reading = True
        self._thread = threading.Thread(
            target=self._reader,
            args=(loop, self._board),
            name=f"msp-{self.name}",
            daemon=True,
        )
        self._thread.start()

    @staticmethod
    def _get_loop() -> Any:
        import asyncio

        return asyncio.get_running_loop()

    def _reader(self, loop: Any, board: Any) -> None:
        while self._reading:
            try:
                fix = self._poll(board)
            except Exception:
                _log.warning("msp poll error; stopping reader", transport=self.name)
                break
            if fix is not None:
                loop.call_soon_threadsafe(self._ingest_nowait, self._to_frame(fix))
            time.sleep(self._poll_interval)

    def _to_frame(self, fix: dict[str, Any]) -> bytes:
        self._seq += 1
        frame = {
            "src": self._source_uid,
            "callsign": self._callsign,
            "msg_id": f"{self._source_uid}:{self._seq}",
            "ts": self._clock.now(),
            "lat": fix["lat"] / self._coord_scale,
            "lon": fix["lon"] / self._coord_scale,
            "hae": fix.get("alt", 0) * self._alt_scale,
        }
        return json.dumps(frame).encode("utf-8")

    async def send(self, data: bytes) -> None:
        # Receive-only source.
        return None

    async def stop(self) -> None:
        self._reading = False
        if self._board is not None:
            close = getattr(self._board, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    _log.debug("msp board close error", transport=self.name)
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        await super().stop()


@transport_registry.register("msp_source")
def _make_msp_source(name: str = "msp", **options: Any) -> MspSourceTransport:
    return MspSourceTransport(name=name, **options)
