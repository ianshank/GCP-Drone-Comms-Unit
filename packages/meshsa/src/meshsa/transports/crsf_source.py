"""CRSF telemetry source transport — an FPV aircraft as an ATAK air track.

A receive-only transport that polls a half-duplex CRSF link (an ELRS handset
module on the ground side) for GPS frames and turns each fix into a telemetry
frame for the ``telemetry`` codec — the same seam as
:mod:`meshsa.transports.msp_source` and :mod:`meshsa.transports.mavlink_source`,
so an FPV aircraft shows up as an ATAK *air* track with no core changes.

Built on :class:`~meshsa.transports.polling_source.PollingSourceTransport`, which
owns the reader-thread lifecycle, event-based shutdown and the position-frame
builder. This module supplies only the CRSF specifics:

  * The link (hardware/pyserial specific) is **injectable**: a fully built
    :class:`~meshsa.fpv.crsf.link.CrsfLink` may be passed as ``link``, otherwise
    one is constructed lazily from :class:`~meshsa.fpv.config.CrsfLinkSettings`
    (whose pyserial default factory is ``# pragma: no cover``). So the plumbing is
    fully tested with a fake ``CrsfSerial`` — no radio, no serial port.
  * Only **GPS (0x02)** frames yield a track — a PLI needs a position. Other CRSF
    telemetry (link statistics, battery, attitude) is decoded-and-ignored here;
    link health belongs to the dedicated :mod:`meshsa.fpv` monitor, not to this
    transport's air-track seam.
  * A single malformed frame must not stop the link: a CRC-valid frame can still
    fail payload-level parsing (:class:`~meshsa.fpv.errors.TelemetryParseError`),
    so per-frame parse errors are caught and dropped, keeping the reader alive.
  * Nothing is hard-coded: device/baud (via ``CrsfLinkSettings``), poll interval,
    identity, and GPS unit scaling (via ``ParserSettings``) are all options.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import structlog

from ..fpv.config import CrsfLinkSettings, ParserSettings
from ..fpv.crsf.link import CrsfLink
from ..fpv.crsf.telemetry import GpsSensor, TelemetryParser
from ..fpv.errors import TelemetryParseError
from ..protocols import Clock
from ..registry import transport_registry
from .polling_source import PollingSourceTransport

_log = structlog.get_logger("meshsa.crsf")

LinkFactory = Callable[[], CrsfLink]


def _default_link_factory(
    settings: CrsfLinkSettings,
) -> LinkFactory:  # pragma: no cover - needs pyserial + radio
    """Build a :class:`CrsfLink` over a real pyserial port (not unit-tested)."""

    def factory() -> CrsfLink:
        return CrsfLink(settings)

    return factory


class CrsfSourceTransport(PollingSourceTransport):
    _thread_prefix = "crsf"

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
        self._settings = settings or CrsfLinkSettings(**_options)
        super().__init__(
            name,
            resource=link,
            factory=link_factory or _default_link_factory(self._settings),
            source_uid=source_uid,
            callsign=callsign,
            clock=clock,
            queue_maxsize=queue_maxsize,
            poll_wait_s=poll_interval_s,
        )
        self._parser = TelemetryParser(parser_settings)

    def _on_open(self, resource: CrsfLink) -> None:
        resource.open()

    def _poll(self, resource: CrsfLink) -> list[bytes]:
        frames: list[bytes] = []
        for frame in resource.poll_inbound():
            try:
                msg = self._parser.parse(frame)
            except TelemetryParseError:
                _log.warning("crsf parse error; dropping frame", transport=self.name)
                continue
            if isinstance(msg, GpsSensor):
                frames.append(self._position_frame(msg.lat_deg, msg.lon_deg, float(msg.altitude_m)))
        return frames


@transport_registry.register("crsf_source")
def _make_crsf_source(name: str = "crsf", **options: Any) -> CrsfSourceTransport:
    return CrsfSourceTransport(name=name, **options)
