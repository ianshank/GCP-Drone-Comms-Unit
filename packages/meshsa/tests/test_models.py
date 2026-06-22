"""Tests for Pydantic model validators in meshsa.models.

Covers boundary values, happy-path defaults, and rejection of invalid inputs
for Position, Telemetry, Attitude, Envelope, and NodeTier.
"""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from meshsa.models import (
    UNKNOWN_ERROR_M,
    Attitude,
    Envelope,
    MessageKind,
    NodeTier,
    Position,
    Telemetry,
)
from meshsa.version import SCHEMA_VERSION

# ---------------------------------------------------------------------------
# NodeTier enum
# ---------------------------------------------------------------------------


class TestNodeTier:
    """NodeTier must expose exactly user / base / backbone."""

    def test_enum_values(self) -> None:
        """All three tier values are accessible and match their string form."""
        assert NodeTier.USER.value == "user"
        assert NodeTier.BASE.value == "base"
        assert NodeTier.BACKBONE.value == "backbone"

    def test_enum_count(self) -> None:
        """Exactly three tiers exist."""
        assert len(NodeTier) == 3

    def test_enum_is_str(self) -> None:
        """NodeTier members behave as plain strings."""
        assert isinstance(NodeTier.USER, str)
        assert NodeTier.USER == "user"


# ---------------------------------------------------------------------------
# Position validators
# ---------------------------------------------------------------------------


class TestPositionHappy:
    """Valid Position construction and default values."""

    def test_minimal_valid(self) -> None:
        """Lat/lon only should succeed with defaults for hae, ce, le."""
        pos = Position(lat=0.0, lon=0.0)
        assert pos.hae == 0.0
        assert pos.ce == UNKNOWN_ERROR_M
        assert pos.le == UNKNOWN_ERROR_M
        assert pos.course_deg is None
        assert pos.speed_ms is None

    def test_full_valid(self) -> None:
        """All fields populated with valid values."""
        pos = Position(
            lat=34.0,
            lon=-118.0,
            hae=100.0,
            ce=5.0,
            le=10.0,
            course_deg=270.0,
            speed_ms=15.5,
        )
        assert pos.lat == 34.0
        assert pos.speed_ms == 15.5


class TestPositionLat:
    """Position._lat_range: [-90, 90]."""

    @pytest.mark.parametrize("lat", [-90.0, 0.0, 45.0, 90.0])
    def test_lat_valid_boundaries(self, lat: float) -> None:
        """Boundary and interior values within [-90, 90] are accepted."""
        pos = Position(lat=lat, lon=0.0)
        assert pos.lat == lat

    @pytest.mark.parametrize("lat", [-90.01, 91.0, -100.0, 180.0])
    def test_lat_out_of_range(self, lat: float) -> None:
        """Values outside [-90, 90] raise ValidationError."""
        with pytest.raises(ValidationError, match="lat out of range"):
            Position(lat=lat, lon=0.0)


class TestPositionLon:
    """Position._lon_range: [-180, 180]."""

    @pytest.mark.parametrize("lon", [-180.0, 0.0, 90.0, 180.0])
    def test_lon_valid_boundaries(self, lon: float) -> None:
        """Boundary and interior values within [-180, 180] are accepted."""
        pos = Position(lat=0.0, lon=lon)
        assert pos.lon == lon

    @pytest.mark.parametrize("lon", [-180.01, 180.01, -200.0, 360.0])
    def test_lon_out_of_range(self, lon: float) -> None:
        """Values outside [-180, 180] raise ValidationError."""
        with pytest.raises(ValidationError, match="lon out of range"):
            Position(lat=0.0, lon=lon)


class TestPositionCourse:
    """Position._course_range: [0, 360) — half-open on the right."""

    @pytest.mark.parametrize("course", [0.0, 1.0, 179.99, 359.99])
    def test_course_valid_boundaries(self, course: float) -> None:
        """Values in [0, 360) are accepted."""
        pos = Position(lat=0.0, lon=0.0, course_deg=course)
        assert pos.course_deg == course

    def test_course_none_valid(self) -> None:
        """None is the default and always accepted."""
        pos = Position(lat=0.0, lon=0.0, course_deg=None)
        assert pos.course_deg is None

    @pytest.mark.parametrize("course", [360.0, 361.0, -0.01, -1.0])
    def test_course_out_of_range(self, course: float) -> None:
        """Values at or above 360 or below 0 are rejected."""
        with pytest.raises(ValidationError, match="course_deg out of range"):
            Position(lat=0.0, lon=0.0, course_deg=course)


class TestPositionSpeed:
    """Position._speed_nonneg: finite and >= 0."""

    @pytest.mark.parametrize("speed", [0.0, 0.01, 100.0, 999999.0])
    def test_speed_valid(self, speed: float) -> None:
        """Non-negative finite values are accepted."""
        pos = Position(lat=0.0, lon=0.0, speed_ms=speed)
        assert pos.speed_ms == speed

    def test_speed_none_valid(self) -> None:
        """None is the default and always accepted."""
        pos = Position(lat=0.0, lon=0.0, speed_ms=None)
        assert pos.speed_ms is None

    @pytest.mark.parametrize("speed", [-0.01, -1.0])
    def test_speed_negative(self, speed: float) -> None:
        """Negative values are rejected."""
        with pytest.raises(ValidationError, match="speed_ms must be a finite value"):
            Position(lat=0.0, lon=0.0, speed_ms=speed)

    @pytest.mark.parametrize("speed", [math.nan, math.inf, -math.inf])
    def test_speed_non_finite(self, speed: float) -> None:
        """NaN and infinities are rejected."""
        with pytest.raises(ValidationError, match="speed_ms must be a finite value"):
            Position(lat=0.0, lon=0.0, speed_ms=speed)


class TestPositionAltitude:
    """Position.hae accepts any finite float (no explicit validator)."""

    @pytest.mark.parametrize("hae", [-1000.0, 0.0, 8848.0, 50000.0])
    def test_altitude_valid(self, hae: float) -> None:
        """Arbitrary finite altitudes are accepted."""
        pos = Position(lat=0.0, lon=0.0, hae=hae)
        assert pos.hae == hae


# ---------------------------------------------------------------------------
# Telemetry validators
# ---------------------------------------------------------------------------


class TestTelemetryHappy:
    """Valid Telemetry construction with defaults."""

    def test_all_none_defaults(self) -> None:
        """All fields default to None."""
        t = Telemetry()
        assert t.battery_v is None
        assert t.battery_pct is None
        assert t.current_a is None
        assert t.attitude is None

    def test_full_valid(self) -> None:
        """All fields with valid values."""
        t = Telemetry(
            battery_v=12.6,
            battery_pct=85,
            current_a=-2.5,
            attitude=Attitude(roll_deg=5.0, pitch_deg=-3.0, yaw_deg=180.0),
        )
        assert t.battery_v == 12.6
        assert t.battery_pct == 85
        assert t.current_a == -2.5
        assert t.attitude is not None


class TestTelemetryBatteryV:
    """Telemetry._battery_v_nonneg: finite and >= 0."""

    @pytest.mark.parametrize("v", [0.0, 0.01, 12.6, 100.0])
    def test_battery_v_valid(self, v: float) -> None:
        """Non-negative finite voltages are accepted."""
        t = Telemetry(battery_v=v)
        assert t.battery_v == v

    @pytest.mark.parametrize("v", [-0.01, -12.0])
    def test_battery_v_negative(self, v: float) -> None:
        """Negative voltages are rejected."""
        with pytest.raises(ValidationError, match="battery_v must be a finite value"):
            Telemetry(battery_v=v)

    @pytest.mark.parametrize("v", [math.nan, math.inf, -math.inf])
    def test_battery_v_non_finite(self, v: float) -> None:
        """NaN and infinities are rejected."""
        with pytest.raises(ValidationError, match="battery_v must be a finite value"):
            Telemetry(battery_v=v)


class TestTelemetryBatteryPct:
    """Telemetry._battery_pct_range: [0, 100]."""

    @pytest.mark.parametrize("pct", [0, 1, 50, 99, 100])
    def test_battery_pct_valid(self, pct: int) -> None:
        """Boundary and interior values in [0, 100] are accepted."""
        t = Telemetry(battery_pct=pct)
        assert t.battery_pct == pct

    @pytest.mark.parametrize("pct", [-1, 101, -100, 200])
    def test_battery_pct_out_of_range(self, pct: int) -> None:
        """Values outside [0, 100] raise ValidationError."""
        with pytest.raises(ValidationError, match="battery_pct out of range"):
            Telemetry(battery_pct=pct)


class TestTelemetryCurrentA:
    """Telemetry._current_finite: must be finite (no sign constraint)."""

    @pytest.mark.parametrize("current", [-10.0, -0.01, 0.0, 5.5, 100.0])
    def test_current_a_valid(self, current: float) -> None:
        """Any finite float is accepted (negative is valid for discharge)."""
        t = Telemetry(current_a=current)
        assert t.current_a == current

    @pytest.mark.parametrize("current", [math.nan, math.inf, -math.inf])
    def test_current_a_non_finite(self, current: float) -> None:
        """NaN and infinities are rejected."""
        with pytest.raises(ValidationError, match="current_a must be a finite value"):
            Telemetry(current_a=current)


# ---------------------------------------------------------------------------
# Attitude
# ---------------------------------------------------------------------------


class TestAttitude:
    """Attitude model: all-None defaults, any float accepted."""

    def test_all_none_defaults(self) -> None:
        """All fields default to None."""
        a = Attitude()
        assert a.roll_deg is None
        assert a.pitch_deg is None
        assert a.yaw_deg is None

    @pytest.mark.parametrize(
        "roll, pitch, yaw",
        [
            (0.0, 0.0, 0.0),
            (-180.0, -90.0, -360.0),
            (180.0, 90.0, 360.0),
            (999.0, -999.0, 0.001),
        ],
    )
    def test_any_float_accepted(
        self,
        roll: float,
        pitch: float,
        yaw: float,
    ) -> None:
        """Attitude has no range validators, any float is accepted."""
        a = Attitude(roll_deg=roll, pitch_deg=pitch, yaw_deg=yaw)
        assert a.roll_deg == roll
        assert a.pitch_deg == pitch
        assert a.yaw_deg == yaw


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------


class TestEnvelope:
    """Envelope defaults and construction."""

    def test_schema_version_default(self) -> None:
        """schema_version defaults to the current SCHEMA_VERSION constant."""
        env = Envelope(
            msg_id="m-1",
            ts=1000.0,
            source_uid="node-a",
            kind=MessageKind.PLI,
        )
        assert env.schema_version == SCHEMA_VERSION

    def test_schema_version_explicit(self) -> None:
        """An explicit schema_version overrides the default."""
        env = Envelope(
            schema_version=42,
            msg_id="m-2",
            ts=1001.0,
            source_uid="node-b",
            kind=MessageKind.CHAT,
        )
        assert env.schema_version == 42

    def test_payload_default_empty(self) -> None:
        """Payload defaults to an empty dict."""
        env = Envelope(
            msg_id="m-3",
            ts=1002.0,
            source_uid="node-c",
            kind=MessageKind.STATUS,
        )
        assert env.payload == {}

    def test_payload_populated(self) -> None:
        """Payload accepts arbitrary dict content."""
        data = {"key": "value", "nested": [1, 2, 3]}
        env = Envelope(
            msg_id="m-4",
            ts=1003.0,
            source_uid="node-d",
            kind=MessageKind.MARKER,
            payload=data,
        )
        assert env.payload == data
