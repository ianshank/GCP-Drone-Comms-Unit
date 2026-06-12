"""Pure CRSF telemetry parsers (§5.1).

All multi-byte telemetry payloads are **big-endian** (``struct '>'``). RSSI
negation and unit scaling happen here and nowhere else. Unknown frame types
return ``None`` and bump a per-type counter — never an exception; malformed
*known* types raise :class:`meshsa.fpv.errors.TelemetryParseError`.

No I/O, no clocks, no threads — given the same frame and settings, ``parse`` is
a deterministic map, which is why this module is held at 100% coverage.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

import structlog

from ..config import ParserSettings
from ..errors import TelemetryParseError
from .frame import CrsfFrame, CrsfFrameType

_log = structlog.get_logger("meshsa.fpv.crsf")

#: TX-power enum (index -> milliwatts) per the CRSF LINK_STATISTICS spec.
_TX_POWER_MW: tuple[int, ...] = (0, 10, 25, 100, 500, 1000, 2000, 250, 50)

#: Known frame types that carry no modelled telemetry: parsed-and-ignored at
#: debug, never counted as "unknown" (§2.2).
_IGNORED_TYPES: frozenset[int] = frozenset(
    {
        CrsfFrameType.RC_CHANNELS_PACKED,
        CrsfFrameType.GPS,
        CrsfFrameType.DEVICE_PING,
        CrsfFrameType.DEVICE_INFO,
        CrsfFrameType.RADIO_ID,
    }
)


@dataclass(frozen=True)
class LinkStatistics:
    """0x14 LINK_STATISTICS — the primary health signal (module-side)."""

    uplink_rssi_ant1_dbm: int
    uplink_rssi_ant2_dbm: int
    uplink_lq: int
    uplink_snr_db: int
    active_antenna: int
    rf_mode: int
    uplink_tx_power_mw: int | None
    downlink_rssi_dbm: int
    downlink_lq: int
    downlink_snr_db: int


@dataclass(frozen=True)
class BatterySensor:
    """0x08 BATTERY_SENSOR — requires FC telemetry; scales are configurable."""

    voltage: float
    current: float
    fuel_drawn_mah: int
    remaining_pct: int


@dataclass(frozen=True)
class Attitude:
    """0x1E ATTITUDE — pitch/roll/yaw in radians (scaled from rad*10000)."""

    pitch_rad: float
    roll_rad: float
    yaw_rad: float


@dataclass(frozen=True)
class FlightMode:
    """0x21 FLIGHT_MODE — null-terminated ASCII; ``is_failsafe`` flags ``!FS!``."""

    mode: str
    is_failsafe: bool


#: The closed set of telemetry messages the parser can emit.
TelemetryMessage = LinkStatistics | BatterySensor | Attitude | FlightMode


class TelemetryParser:
    """Decode CRSF frames into typed telemetry messages (pure, settings-driven)."""

    def __init__(self, settings: ParserSettings | None = None) -> None:
        self._s = settings or ParserSettings()
        #: Count of frames seen per unknown (unmodelled, non-ignored) type.
        self.unknown_counts: dict[int, int] = {}

    def parse(self, frame: CrsfFrame) -> TelemetryMessage | None:
        """Return a typed message, or ``None`` for unknown/ignored types.

        Raises :class:`TelemetryParseError` only when a *known* telemetry type
        has a payload that fails length validation.
        """
        ftype = frame.type
        if ftype == CrsfFrameType.LINK_STATISTICS:
            return self._link_statistics(frame.payload)
        if ftype == CrsfFrameType.BATTERY_SENSOR:
            return self._battery(frame.payload)
        if ftype == CrsfFrameType.ATTITUDE:
            return self._attitude(frame.payload)
        if ftype == CrsfFrameType.FLIGHT_MODE:
            return self._flight_mode(frame.payload)
        if ftype in _IGNORED_TYPES:
            _log.debug("ignoring known non-telemetry frame", type=frame.type_name)
            return None
        self.unknown_counts[ftype] = self.unknown_counts.get(ftype, 0) + 1
        _log.debug("unknown telemetry type", type=f"0x{ftype:02X}")
        return None

    @staticmethod
    def _require(payload: bytes, n: int, what: str) -> None:
        if len(payload) != n:
            raise TelemetryParseError(f"{what}: expected {n} bytes, got {len(payload)}")

    def _link_statistics(self, payload: bytes) -> LinkStatistics:
        self._require(payload, 10, "LINK_STATISTICS")
        (
            rssi1,
            rssi2,
            up_lq,
            up_snr,
            ant,
            rf_mode,
            tx_power_idx,
            down_rssi,
            down_lq,
            down_snr,
        ) = struct.unpack(">BBBbBBBBBb", payload)
        tx_power = _TX_POWER_MW[tx_power_idx] if tx_power_idx < len(_TX_POWER_MW) else None
        return LinkStatistics(
            uplink_rssi_ant1_dbm=-rssi1,  # stored as dBm*-1 on the wire
            uplink_rssi_ant2_dbm=-rssi2,
            uplink_lq=up_lq,
            uplink_snr_db=up_snr,
            active_antenna=ant,
            rf_mode=rf_mode,
            uplink_tx_power_mw=tx_power,
            downlink_rssi_dbm=-down_rssi,
            downlink_lq=down_lq,
            downlink_snr_db=down_snr,
        )

    def _battery(self, payload: bytes) -> BatterySensor:
        self._require(payload, 8, "BATTERY_SENSOR")
        voltage_raw, current_raw = struct.unpack(">HH", payload[:4])
        fuel = int.from_bytes(payload[4:7], "big")  # u24 mAh
        remaining = payload[7]
        return BatterySensor(
            voltage=voltage_raw * self._s.telemetry_voltage_scale,
            current=current_raw * self._s.telemetry_current_scale,
            fuel_drawn_mah=fuel,
            remaining_pct=remaining,
        )

    def _attitude(self, payload: bytes) -> Attitude:
        self._require(payload, 6, "ATTITUDE")
        pitch, roll, yaw = struct.unpack(">hhh", payload)
        scale = self._s.attitude_rad_scale
        return Attitude(pitch_rad=pitch * scale, roll_rad=roll * scale, yaw_rad=yaw * scale)

    def _flight_mode(self, payload: bytes) -> FlightMode:
        if not payload:
            raise TelemetryParseError("FLIGHT_MODE: empty payload")
        text = payload.split(b"\x00", 1)[0].decode("ascii", errors="replace")
        return FlightMode(mode=text, is_failsafe=self._s.failsafe_marker in text)
