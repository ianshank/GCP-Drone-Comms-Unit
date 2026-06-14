"""Pure CRSF telemetry parsers + endianness lock-in.

Endianness lock-in (big-endian must be enforced) is only meaningful for frames
with **multi-byte** fields: BATTERY_SENSOR (u16/u16/u24) and ATTITUDE (i16 x3).
LINK_STATISTICS is all u8/i8, so byte order is a no-op there — it is instead
validated by value semantics (RSSI negation, LQ range, signed SNR).
"""

from __future__ import annotations

import struct

import pytest

from meshsa.fpv.config import ParserSettings
from meshsa.fpv.crsf.frame import CrsfFrame, CrsfFrameType
from meshsa.fpv.crsf.telemetry import (
    Attitude,
    BatterySensor,
    FlightMode,
    GpsSensor,
    LinkStatistics,
    TelemetryParser,
)
from meshsa.fpv.errors import TelemetryParseError


def _frame(ftype: int, payload: bytes) -> CrsfFrame:
    return CrsfFrame(addr=0xC8, type=ftype, payload=payload)


# --------------------------------------------------------------------------- #
# LINK_STATISTICS — value semantics (single-byte fields, endianness-agnostic)  #
# --------------------------------------------------------------------------- #


def test_link_statistics_golden_value_semantics():
    # rssi1=70(-70dBm), rssi2=80, lq=99, snr=-5, ant=1, rf_mode=6,
    # tx_power_idx=3(=100mW), down_rssi=60, down_lq=100, down_snr=8
    payload = struct.pack(">BBBbBBBBBb", 70, 80, 99, -5, 1, 6, 3, 60, 100, 8)
    msg = TelemetryParser().parse(_frame(CrsfFrameType.LINK_STATISTICS, payload))
    assert isinstance(msg, LinkStatistics)
    assert msg.uplink_rssi_ant1_dbm == -70  # negation applied
    assert msg.uplink_rssi_ant2_dbm == -80
    assert msg.uplink_lq == 99
    assert msg.uplink_snr_db == -5  # signed
    assert msg.active_antenna == 1
    assert msg.rf_mode == 6
    assert msg.uplink_tx_power_mw == 100  # index 3 -> 100 mW
    assert msg.downlink_rssi_dbm == -60
    assert msg.downlink_lq == 100
    assert msg.downlink_snr_db == 8


def test_link_statistics_unknown_tx_power_index_is_none():
    payload = struct.pack(">BBBbBBBBBb", 70, 80, 99, -5, 1, 6, 250, 60, 100, 8)
    msg = TelemetryParser().parse(_frame(CrsfFrameType.LINK_STATISTICS, payload))
    assert isinstance(msg, LinkStatistics)
    assert msg.uplink_tx_power_mw is None


def test_link_statistics_truncated_raises():
    with pytest.raises(TelemetryParseError, match="LINK_STATISTICS"):
        TelemetryParser().parse(_frame(CrsfFrameType.LINK_STATISTICS, b"\x00" * 9))


# --------------------------------------------------------------------------- #
# BATTERY_SENSOR — multi-byte: endianness lock-in                              #
# --------------------------------------------------------------------------- #


def test_battery_golden_and_configurable_scale():
    # voltage_raw=168 (->16.8V at 0.1), current_raw=52 (->5.2A), fuel=1234mAh, rem=87%
    payload = struct.pack(">HH", 168, 52) + (1234).to_bytes(3, "big") + bytes([87])
    msg = TelemetryParser().parse(_frame(CrsfFrameType.BATTERY_SENSOR, payload))
    assert isinstance(msg, BatterySensor)
    assert msg.voltage == pytest.approx(16.8)
    assert msg.current == pytest.approx(5.2)
    assert msg.fuel_drawn_mah == 1234
    assert msg.remaining_pct == 87
    # Configurable scale (firmware ambiguity) flows from settings.
    msg2 = TelemetryParser(ParserSettings(telemetry_voltage_scale=0.01)).parse(
        _frame(CrsfFrameType.BATTERY_SENSOR, payload)
    )
    assert isinstance(msg2, BatterySensor)
    assert msg2.voltage == pytest.approx(1.68)


def test_battery_endianness_lock_in():
    # voltage_raw=0x0102 big-endian = 258; little-endian would read 0x0201 = 513.
    payload = struct.pack(">HH", 0x0102, 0x0304) + (0).to_bytes(3, "big") + bytes([50])
    msg = TelemetryParser(ParserSettings(telemetry_voltage_scale=1.0)).parse(
        _frame(CrsfFrameType.BATTERY_SENSOR, payload)
    )
    assert isinstance(msg, BatterySensor)
    assert msg.voltage == pytest.approx(258.0)  # big-endian correct
    # A little-endian decode of the same bytes yields a DIFFERENT (wrong) value.
    wrong = struct.unpack("<H", payload[:2])[0]
    assert wrong == 0x0201
    assert wrong != 258


# --------------------------------------------------------------------------- #
# ATTITUDE — multi-byte signed: endianness lock-in + scaling                   #
# --------------------------------------------------------------------------- #


def test_attitude_golden_scaling_and_sign():
    payload = struct.pack(">hhh", 15708, -7854, 0)  # ~pi/2, ~-pi/4, 0 (rad*10000)
    msg = TelemetryParser().parse(_frame(CrsfFrameType.ATTITUDE, payload))
    assert isinstance(msg, Attitude)
    assert msg.pitch_rad == pytest.approx(1.5708)
    assert msg.roll_rad == pytest.approx(-0.7854)
    assert msg.yaw_rad == pytest.approx(0.0)


def test_attitude_endianness_lock_in():
    payload = struct.pack(">hhh", 0x0102, 0, 0)
    msg = TelemetryParser(ParserSettings(attitude_rad_scale=1.0)).parse(
        _frame(CrsfFrameType.ATTITUDE, payload)
    )
    assert isinstance(msg, Attitude)
    assert msg.pitch_rad == pytest.approx(258.0)  # big-endian
    assert struct.unpack("<h", payload[:2])[0] == 0x0201  # little-endian disagrees


def test_attitude_truncated_raises():
    with pytest.raises(TelemetryParseError, match="ATTITUDE"):
        TelemetryParser().parse(_frame(CrsfFrameType.ATTITUDE, b"\x00" * 4))


# --------------------------------------------------------------------------- #
# FLIGHT_MODE — failsafe flag                                                  #
# --------------------------------------------------------------------------- #


def test_flight_mode_parses_and_flags_failsafe():
    p = TelemetryParser()
    ok = p.parse(_frame(CrsfFrameType.FLIGHT_MODE, b"ANGL\x00"))
    assert isinstance(ok, FlightMode)
    assert ok.mode == "ANGL"
    assert ok.is_failsafe is False
    fs = p.parse(_frame(CrsfFrameType.FLIGHT_MODE, b"!FS!\x00"))
    assert isinstance(fs, FlightMode)
    assert fs.is_failsafe is True


def test_flight_mode_custom_marker():
    p = TelemetryParser(ParserSettings(failsafe_marker="LAND"))
    msg = p.parse(_frame(CrsfFrameType.FLIGHT_MODE, b"LAND\x00"))
    assert isinstance(msg, FlightMode)
    assert msg.is_failsafe is True


def test_flight_mode_empty_raises():
    with pytest.raises(TelemetryParseError, match="empty"):
        TelemetryParser().parse(_frame(CrsfFrameType.FLIGHT_MODE, b""))


# --------------------------------------------------------------------------- #
# GPS — big-endian position/velocity, configurable scaling                     #
# --------------------------------------------------------------------------- #


def test_gps_golden_value_and_scaling():
    # lat=37.7749°, lon=-122.4194°, speed=12.3 km/h, heading=180.0°,
    # altitude raw 1120 -> 120 m (the +1000 m offset removed), 9 satellites.
    payload = struct.pack(">iiHHHB", 377749000, -1224194000, 123, 18000, 1120, 9)
    msg = TelemetryParser().parse(_frame(CrsfFrameType.GPS, payload))
    assert isinstance(msg, GpsSensor)
    assert msg.lat_deg == pytest.approx(37.7749)
    assert msg.lon_deg == pytest.approx(-122.4194)  # signed i32 (big-endian)
    assert msg.ground_speed_kmh == pytest.approx(12.3)
    assert msg.heading_deg == pytest.approx(180.0)
    assert msg.altitude_m == 120  # 1120 - 1000 m offset
    assert msg.satellites == 9


def test_gps_wrong_length_raises():
    with pytest.raises(TelemetryParseError, match="GPS"):
        TelemetryParser().parse(_frame(CrsfFrameType.GPS, b"\x00" * 14))


# --------------------------------------------------------------------------- #
# Unknown vs ignored types                                                     #
# --------------------------------------------------------------------------- #


def test_unknown_type_returns_none_and_counts():
    p = TelemetryParser()
    assert p.parse(_frame(0x7F, b"\x00\x01")) is None
    assert p.parse(_frame(0x7F, b"\x02")) is None
    assert p.unknown_counts == {0x7F: 2}


def test_ignored_known_types_return_none_without_counting():
    p = TelemetryParser()
    for ftype in (
        CrsfFrameType.RC_CHANNELS_PACKED,
        CrsfFrameType.DEVICE_INFO,
        CrsfFrameType.DEVICE_PING,
        CrsfFrameType.RADIO_ID,
    ):
        assert p.parse(_frame(ftype, b"\x00\x00")) is None
    assert p.unknown_counts == {}  # ignored != unknown
