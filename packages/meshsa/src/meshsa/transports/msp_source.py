"""Betaflight MSP telemetry source transport (YAMSPy / MultiWii Serial Protocol).

A receive-only transport that polls a Betaflight flight controller over serial for
position (MSP_RAW_GPS) and turns each fix into a telemetry frame for the
``telemetry`` codec — the same seam as :mod:`meshsa.transports.mavlink_source`, so a
drone/FC shows up as an ATAK track with no core changes.

Built on :class:`~meshsa.transports.polling_source.PollingSourceTransport` (which
owns the reader thread, event-based shutdown and the frame builder). This module
supplies only the MSP specifics:
  * The MSP request/response poll (hardware/YAMSPy specific) is an **injectable**
    ``poll`` callable; its default talks to a real ``yamspy.MSPy`` board and is
    ``# pragma: no cover``. The board itself is injected too (``board`` /
    ``board_factory``). So the transport plumbing is fully tested with fakes; no
    FC, no serial, no socat.
  * Nothing is hard-coded: device/baud, poll interval, identity, coordinate/alt
    scaling and the clock are parameters/config options. Coordinate scaling is
    configurable because MSP GPS units vary by firmware (Betaflight reports lat/lon
    in 1e7 degrees; ``coord_scale`` defaults accordingly).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..protocols import Clock
from ..registry import transport_registry
from .polling_source import PollingSourceTransport

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


class MspSourceTransport(PollingSourceTransport):
    _thread_prefix = "msp"

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
        log_every_n: int = 100,
        log_interval_s: float = 30.0,
        **_options: Any,
    ) -> None:
        super().__init__(
            name,
            resource=board,
            factory=board_factory or _default_board_factory(_options),
            source_uid=source_uid,
            callsign=callsign,
            clock=clock,
            queue_maxsize=queue_maxsize,
            poll_wait_s=poll_interval_s,
            log_every_n=log_every_n,
            log_interval_s=log_interval_s,
        )
        self._poll_fn = poll or _default_poll
        self._coord_scale = coord_scale
        self._alt_scale = alt_scale

    def _poll(self, resource: Any) -> list[bytes]:
        fix = self._poll_fn(resource)
        if fix is None:
            return []
        return [
            self._position_frame(
                fix["lat"] / self._coord_scale,
                fix["lon"] / self._coord_scale,
                fix.get("alt", 0) * self._alt_scale,
            )
        ]


@transport_registry.register("msp_source")
def _make_msp_source(name: str = "msp", **options: Any) -> MspSourceTransport:
    return MspSourceTransport(name=name, **options)
