import pytest
from pydantic import ValidationError

from meshsa import (
    Attitude,
    Envelope,
    MessageKind,
    NodeInfo,
    NodeTier,
    PliPayload,
    Position,
    Telemetry,
)
from meshsa.version import SCHEMA_VERSION, is_compatible


def test_compatibility_window():
    assert is_compatible(SCHEMA_VERSION)
    assert not is_compatible(SCHEMA_VERSION + 1)
    assert not is_compatible(0)


def test_position_bounds_ok():
    p = Position(lat=45.0, lon=-120.0)
    assert p.hae == 0.0


@pytest.mark.parametrize("lat,lon", [(91, 0), (-91, 0), (0, 181), (0, -181)])
def test_position_bounds_reject(lat, lon):
    with pytest.raises(ValidationError):
        Position(lat=lat, lon=lon)


def test_envelope_defaults_schema_version():
    e = Envelope(msg_id="x", ts=1.0, source_uid="u", kind=MessageKind.PLI)
    assert e.schema_version == SCHEMA_VERSION
    assert e.payload == {}


def test_nodeinfo_default_tier():
    assert NodeInfo(uid="u", callsign="c").tier == NodeTier.USER


def test_position_course_speed_default_none():
    p = Position(lat=10.0, lon=20.0)
    assert p.course_deg is None
    assert p.speed_ms is None


def test_position_course_speed_accepts_valid():
    p = Position(lat=10.0, lon=20.0, course_deg=359.9, speed_ms=12.5)
    assert p.course_deg == pytest.approx(359.9)
    assert p.speed_ms == pytest.approx(12.5)


@pytest.mark.parametrize("course", [-1.0, 360.0, 400.0])
def test_position_course_out_of_range_rejected(course):
    with pytest.raises(ValidationError):
        Position(lat=0.0, lon=0.0, course_deg=course)


def test_position_negative_speed_rejected():
    with pytest.raises(ValidationError):
        Position(lat=0.0, lon=0.0, speed_ms=-0.1)


def test_attitude_optional_fields_default_none():
    a = Attitude()
    assert a.roll_deg is None and a.pitch_deg is None and a.yaw_deg is None
    a2 = Attitude(roll_deg=1.0, pitch_deg=-2.0, yaw_deg=180.0)
    assert a2.roll_deg == pytest.approx(1.0)
    assert a2.pitch_deg == pytest.approx(-2.0)
    assert a2.yaw_deg == pytest.approx(180.0)


def test_telemetry_optional_fields_default_none():
    t = Telemetry()
    assert t.battery_v is None
    assert t.battery_pct is None
    assert t.current_a is None
    assert t.attitude is None
    t2 = Telemetry(battery_v=11.1, battery_pct=80, current_a=3.5, attitude=Attitude(roll_deg=1.0))
    assert t2.battery_pct == 80
    assert t2.attitude is not None and t2.attitude.roll_deg == pytest.approx(1.0)


def test_telemetry_valid_battery_bounds_pass():
    t = Telemetry(battery_v=0.0, battery_pct=0)
    assert t.battery_v == pytest.approx(0.0)
    assert t.battery_pct == 0
    t2 = Telemetry(battery_v=12.6, battery_pct=100)
    assert t2.battery_pct == 100


def test_telemetry_negative_battery_v_rejected():
    with pytest.raises(ValidationError):
        Telemetry(battery_v=-1.0)


@pytest.mark.parametrize("battery_pct", [-1, 101, 150])
def test_telemetry_battery_pct_out_of_range_rejected(battery_pct):
    with pytest.raises(ValidationError):
        Telemetry(battery_pct=battery_pct)


def test_plipayload_telemetry_default_none():
    p = PliPayload(node=NodeInfo(uid="u", callsign="c"), position=Position(lat=1.0, lon=2.0))
    assert p.telemetry is None


def test_plain_payload_has_no_null_keys():
    # exclude_none guard: a default position/payload must not leak null richer keys.
    pos_dump = Position(lat=1.0, lon=2.0).model_dump(exclude_none=True)
    assert "course_deg" not in pos_dump
    assert "speed_ms" not in pos_dump

    payload = PliPayload(
        node=NodeInfo(uid="u", callsign="c"), position=Position(lat=1.0, lon=2.0)
    ).model_dump(exclude_none=True)
    assert "telemetry" not in payload
    assert "course_deg" not in payload["position"]
    assert "speed_ms" not in payload["position"]


def test_default_clock_and_id_factory():
    from meshsa import SystemClock, UuidFactory

    assert SystemClock().now() > 0
    a, b = UuidFactory().new_id(), UuidFactory().new_id()
    assert a != b and len(a) == 32


def test_warn_deprecated_emits_deprecationwarning():
    import pytest

    from meshsa.version import warn_deprecated

    with pytest.warns(DeprecationWarning, match="old_field"):
        warn_deprecated("old_field", "new_field")
    with pytest.warns(DeprecationWarning, match="removal in 0.3.0"):
        warn_deprecated("a", "b", removed_in="0.3.0")
