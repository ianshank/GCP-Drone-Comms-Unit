"""Betaflight MSP telemetry source transport (YAMSPy / MultiWii Serial Protocol).

A receive-only transport that polls a Betaflight flight controller over serial for
position (MSP_RAW_GPS) and turns each sample into a telemetry frame for the
``telemetry`` codec — the same seam as :mod:`meshsa.transports.mavlink_source`, so a
drone/FC shows up as an ATAK track with no core changes.

Built on :class:`~meshsa.transports.polling_source.PollingSourceTransport` (which
owns the reader thread, event-based shutdown, link-health observability and the
guarded resource close). This module supplies only the MSP specifics:
  * The MSP request/response poll (hardware/YAMSPy specific) is an **injectable**
    ``poll`` callable; its default talks to a real ``yamspy.MSPy`` board and is
    ``# pragma: no cover``. The board itself is injected too (``board`` /
    ``board_factory``). So the transport plumbing is fully tested with fakes; no
    FC, no serial, no socat.
  * Nothing is hard-coded: device/baud, poll interval, identity, coordinate/alt
    scaling and the clock are parameters/config options. Coordinate scaling is
    configurable because MSP GPS units vary by firmware (Betaflight reports lat/lon
    in 1e7 degrees; ``coord_scale`` defaults accordingly).
  * **Backwards compatible / bench friendly:** a sample is a loose dict. When it
    carries a GPS fix (``lat``/``lon``), that becomes the position; otherwise, if a
    ``fallback_*`` position is configured (e.g. a GPS-less bench FC), the FC still
    shows as a stationary track. Any extra telemetry the poll reports (battery,
    RSSI, attitude) is rendered into an optional ``remarks`` string. A sample with
    neither a fix nor a fallback yields no frame — the original behaviour.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import structlog

from ..protocols import Clock
from ..registry import transport_registry
from .polling_source import PollingSourceTransport

_log = structlog.get_logger("meshsa.msp")

BoardFactory = Callable[[], Any]
#: A board -> sample mapper. A sample is a loose dict that MAY carry a GPS fix
#: (``lat``/``lon``/``alt`` in raw MSP units) and/or telemetry (``vbat``, ``rssi``,
#: ``amperage``, ``roll``, ``pitch``, ``yaw``). Returns ``None`` when the board had
#: nothing to report.
PollFn = Callable[[Any], "dict[str, Any] | None"]

#: How telemetry sample fields render into the ``remarks`` string (label + format).
#: Iteration order fixes the remarks layout; only present, formattable fields appear.
_REMARK_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("vbat", "VBAT", "{:.1f}V"),
    ("amperage", "CUR", "{:.1f}A"),
    ("rssi", "RSSI", "{:.0f}"),
    ("roll", "ROLL", "{:.0f}"),
    ("pitch", "PITCH", "{:.0f}"),
    ("yaw", "YAW", "{:.0f}"),
)


def _default_board_factory(options: dict[str, Any]) -> BoardFactory:  # pragma: no cover
    def factory() -> Any:
        from yamspy import MSPy

        device = options.get("device", "/dev/ttyACM0")
        board = MSPy(
            device=device,
            loglevel=options.get("loglevel", "WARNING"),
            baudrate=int(options.get("baudrate", 115200)),
        )
        # yamspy.connect returns 0 on success, 1 on failure (swallowing the real error
        # as a log warning). Fail loudly here so a permission/port issue surfaces as a
        # clear message instead of a downstream "poll error" on a half-open port. The
        # most common cause is the user not being in the 'dialout' group, or the FC's
        # serial port being held by Betaflight Configurator.
        if board.connect(trials=board.ser_trials) != 0:
            raise ConnectionError(
                f"could not connect to flight controller at {device} "
                "(check the device path, 'dialout' group membership, and that "
                "Betaflight Configurator is disconnected)"
            )
        return board

    return factory


def _msp_read(board: Any, code: str) -> None:  # pragma: no cover - needs YAMSPy + FC
    """One MSP request/response round-trip; populates the matching board attribute."""
    from yamspy import MSPy

    if board.send_RAW_msg(MSPy.MSPCodes[code], data=[]):
        board.process_recv_data(board.receive_msg())


def _read_gps(board: Any) -> dict[str, Any]:  # pragma: no cover - needs YAMSPy + FC
    """One MSP_RAW_GPS round-trip → {lat,lon,alt} (raw MSP units) if there's a fix, else {}."""
    _msp_read(board, "MSP_RAW_GPS")
    gps = board.GPS_DATA
    if not gps.get("fix"):
        return {}
    return {"lat": gps["lat"], "lon": gps["lon"], "alt": gps.get("alt", 0)}


def _read_analog(board: Any) -> dict[str, Any]:  # pragma: no cover - needs YAMSPy + FC
    """One MSP_ANALOG round-trip → battery voltage (V), rssi (0-1023), amperage (A)."""
    _msp_read(board, "MSP_ANALOG")
    analog = board.ANALOG
    return {
        "vbat": analog.get("voltage"),
        "rssi": analog.get("rssi"),
        "amperage": analog.get("amperage"),
    }


def _read_attitude(board: Any) -> dict[str, Any]:  # pragma: no cover - needs YAMSPy + FC
    """One MSP_ATTITUDE round-trip → roll/pitch/yaw (degrees) from SENSOR_DATA['kinematics']."""
    _msp_read(board, "MSP_ATTITUDE")
    roll, pitch, yaw = board.SENSOR_DATA["kinematics"]
    return {"roll": roll, "pitch": pitch, "yaw": yaw}


#: Per-message MSP readers, each a single request/response — usable as a round-robin set so a
#: caller can read ONE message at a time instead of blocking for all three at once.
DEFAULT_MSP_READERS: tuple[Callable[[Any], dict[str, Any]], ...] = (
    _read_gps,
    _read_analog,
    _read_attitude,
)


def _default_poll(board: Any) -> dict[str, Any] | None:  # pragma: no cover - needs YAMSPy + FC
    """Read GPS + battery/RSSI + attitude over MSP into one sample (three round-trips).

    The GPS read drives the position; the enrichment reads are isolated so a slow/absent
    message degrades to "no remarks" rather than killing the position path. yamspy attribute
    paths verified against the installed library — there is no ``board.ATTITUDE``.
    """
    sample: dict[str, Any] = dict(_read_gps(board))
    for reader in (_read_analog, _read_attitude):
        try:
            sample.update(reader(board))
        except Exception:
            _log.debug("msp telemetry read failed")
    return sample or None


def _resolve_position(
    sample: dict[str, Any] | None,
    *,
    coord_scale: float,
    alt_scale: float,
    fallback_lat: float | None,
    fallback_lon: float | None,
    fallback_hae: float,
) -> tuple[float, float, float] | None:
    """Resolve a sample to (lat, lon, hae) in decimal degrees/metres, or None.

    A GPS fix in the sample wins (scaled by ``coord_scale``/``alt_scale``); else the
    configured fallback position (already in degrees); else no position.
    """
    if sample and sample.get("lat") is not None and sample.get("lon") is not None:
        return (
            sample["lat"] / coord_scale,
            sample["lon"] / coord_scale,
            sample.get("alt", 0) * alt_scale,
        )
    if fallback_lat is not None and fallback_lon is not None:
        return (fallback_lat, fallback_lon, fallback_hae)
    return None


def _render_remarks(sample: dict[str, Any] | None) -> str:
    """Render present, formattable telemetry fields into a CoT remarks string."""
    if not sample:
        return ""
    out: list[str] = []
    for key, label, fmt in _REMARK_FIELDS:
        val = sample.get(key)
        if val is None:
            continue
        try:
            out.append(f"{label} {fmt.format(val)}")
        except (TypeError, ValueError):
            continue
    return " ".join(out)


def build_telemetry_frame(
    sample: dict[str, Any] | None,
    *,
    seq: int,
    source_uid: str,
    callsign: str,
    now: float,
    coord_scale: float = 1e7,
    alt_scale: float = 1.0,
    fallback_lat: float | None = None,
    fallback_lon: float | None = None,
    fallback_hae: float = 0.0,
) -> bytes | None:
    """Map an MSP sample to a ``telemetry`` codec frame, or None if it has no position.

    Pure and stateless — the caller owns ``seq`` (and the message clock via ``now``) — so it
    is reused by both :class:`MspSourceTransport` and the RC pilot daemon without duplication.
    """
    pos = _resolve_position(
        sample,
        coord_scale=coord_scale,
        alt_scale=alt_scale,
        fallback_lat=fallback_lat,
        fallback_lon=fallback_lon,
        fallback_hae=fallback_hae,
    )
    if pos is None:
        return None
    lat, lon, hae = pos
    frame: dict[str, Any] = {
        "src": source_uid,
        "callsign": callsign,
        "msg_id": f"{source_uid}:{seq}",
        "ts": now,
        "lat": lat,
        "lon": lon,
        "hae": hae,
    }
    remarks = _render_remarks(sample)
    if remarks:
        frame["remarks"] = remarks
    return json.dumps(frame).encode("utf-8")


class MspSourceTransport(PollingSourceTransport):
    """MSP flight-source on the shared :class:`PollingSourceTransport` plumbing.

    Adds the MSP specifics on top of the base reader thread: the (injectable) poll,
    coordinate/alt scaling, the optional GPS-less fallback position, and telemetry
    ``remarks`` — all funnelled through the pure :func:`build_telemetry_frame`.
    """

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
        fallback_lat: float | None = None,
        fallback_lon: float | None = None,
        fallback_hae: float = 0.0,
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
        # Fallback position (decimal degrees / metres, NOT scaled by coord_scale) for a
        # GPS-less FC: keeps the track on the map and lets telemetry remarks flow.
        self._fallback_lat = fallback_lat
        self._fallback_lon = fallback_lon
        self._fallback_hae = fallback_hae

    def _poll(self, resource: Any) -> list[bytes]:
        sample = self._poll_fn(resource)
        # Advance the sequence only when a frame is actually produced.
        frame = build_telemetry_frame(
            sample,
            seq=self._seq + 1,
            source_uid=self._source_uid,
            callsign=self._callsign,
            now=self._clock.now(),
            coord_scale=self._coord_scale,
            alt_scale=self._alt_scale,
            fallback_lat=self._fallback_lat,
            fallback_lon=self._fallback_lon,
            fallback_hae=self._fallback_hae,
        )
        if frame is None:
            return []
        self._seq += 1
        return [frame]


@transport_registry.register("msp_source")
def _make_msp_source(name: str = "msp", **options: Any) -> MspSourceTransport:
    return MspSourceTransport(name=name, **options)
