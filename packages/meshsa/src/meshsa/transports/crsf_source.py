"""CRSF telemetry source transport — an FPV aircraft as an ATAK air track.

A receive-only transport that polls a half-duplex CRSF link (an ELRS handset
module on the ground side) for GPS frames and turns each fix into a telemetry
frame for the ``telemetry`` codec — the same seam as
:mod:`meshsa.transports.msp_source` and :mod:`meshsa.transports.mavlink_source`,
so an FPV aircraft shows up as an ATAK *air* track with no core changes.

Design mirrors :mod:`meshsa.transports.msp_source`:
  * The CRSF link (hardware/pyserial specific) is **injectable**: a fully built
    :class:`~meshsa.fpv.crsf.link.CrsfLink` may be passed as ``link``, otherwise
    one is constructed lazily from :class:`~meshsa.fpv.config.CrsfLinkSettings`
    (whose pyserial default factory is ``# pragma: no cover``). So the transport
    plumbing — reader thread, polling, parse, ingest, lifecycle — is fully tested
    with a fake ``CrsfSerial``; no radio, no serial port.
  * Polling runs on a dedicated thread (serial I/O is blocking/timeout-bounded);
    each GPS fix crosses into the asyncio loop via ``call_soon_threadsafe`` onto
    the shared drop-counting ``_ingest_nowait``.
  * Only **GPS (0x02)** frames yield a track — a PLI needs a position. Other CRSF
    telemetry (link statistics, battery, attitude) is decoded-and-ignored here;
    link health belongs to the dedicated :mod:`meshsa.fpv` monitor, not to this
    transport's air-track seam.
  * Nothing is hard-coded: device/baud (via ``CrsfLinkSettings``), poll interval,
    identity, and GPS unit scaling (via ``ParserSettings``) are all options.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from typing import Any

import structlog

from ..fpv.config import CrsfLinkSettings, ParserSettings
from ..fpv.crsf.link import CrsfLink
from ..fpv.crsf.telemetry import GpsSensor, TelemetryParser
from ..protocols import Clock, SystemClock
from ..registry import transport_registry
from .base import AbstractTransport

_log = structlog.get_logger("meshsa.crsf")

LinkFactory = Callable[[], CrsfLink]


def _default_link_factory(
    settings: CrsfLinkSettings,
) -> LinkFactory:  # pragma: no cover - needs pyserial + radio
    """Build a :class:`CrsfLink` over a real pyserial port (not unit-tested)."""

    def factory() -> CrsfLink:
        return CrsfLink(settings)

    return factory


class CrsfSourceTransport(AbstractTransport):
    def __init__(
        self,
        name: str = "crsf",
        *,
        link: CrsfLink | None = None,
        link_factory: LinkFactory | None = None,
        settings: CrsfLinkSettings | None = None,
        parser_settings: ParserSettings | None = None,
        source_uid: str = "uav-1",
        callsign: str | None = None,
        poll_interval_s: float = 1.0,
        clock: Clock | None = None,
        queue_maxsize: int = 1000,
        **_options: Any,
    ) -> None:
        super().__init__(name, queue_maxsize)
        self._settings = settings or CrsfLinkSettings(**_options)
        self._link = link
        self._factory = link_factory or _default_link_factory(self._settings)
        self._parser = TelemetryParser(parser_settings)
        self._source_uid = source_uid
        self._callsign = callsign or source_uid
        self._poll_interval = poll_interval_s
        self._clock = clock or SystemClock()
        self._thread: threading.Thread | None = None
        self._reading = False
        self._seq = 0

    async def start(self) -> None:
        await super().start()
        loop = self._get_loop()
        if self._link is None:
            self._link = self._factory()  # pragma: no cover - exercised via injection
        self._link.open()
        self._reading = True
        self._thread = threading.Thread(
            target=self._reader,
            args=(loop, self._link),
            name=f"crsf-{self.name}",
            daemon=True,
        )
        self._thread.start()

    @staticmethod
    def _get_loop() -> Any:
        import asyncio

        return asyncio.get_running_loop()

    def _reader(self, loop: Any, link: CrsfLink) -> None:
        while self._reading:
            try:
                frames = link.poll_inbound()
            except Exception:
                _log.warning("crsf poll error; stopping reader", transport=self.name)
                break
            for frame in frames:
                msg = self._parser.parse(frame)
                if isinstance(msg, GpsSensor):
                    loop.call_soon_threadsafe(self._ingest_nowait, self._to_frame(msg))
            time.sleep(self._poll_interval)

    def _to_frame(self, gps: GpsSensor) -> bytes:
        self._seq += 1
        frame = {
            "src": self._source_uid,
            "callsign": self._callsign,
            "msg_id": f"{self._source_uid}:{self._seq}",
            "ts": self._clock.now(),
            "lat": gps.lat_deg,
            "lon": gps.lon_deg,
            "hae": float(gps.altitude_m),
        }
        return json.dumps(frame).encode("utf-8")

    async def send(self, data: bytes) -> None:
        # Receive-only source.
        return None

    async def stop(self) -> None:
        self._reading = False
        if self._link is not None:
            self._link.close()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        await super().stop()


@transport_registry.register("crsf_source")
def _make_crsf_source(name: str = "crsf", **options: Any) -> CrsfSourceTransport:
    return CrsfSourceTransport(name=name, **options)
