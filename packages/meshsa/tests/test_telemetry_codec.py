import json

import pytest

from meshsa import (
    Envelope,
    MeshSAError,
    MessageKind,
    TelemetryCodec,
    codec_registry,
)
from meshsa.version import SCHEMA_VERSION


def _frame(**over):
    base = {
        "src": "uav-1",
        "callsign": "UAV1",
        "msg_id": "uav-1:1",
        "ts": 1_700_000_000.0,
        "lat": 37.7749,
        "lon": -122.4194,
        "hae": 100.0,
    }
    base.update(over)
    return json.dumps(base).encode("utf-8")


def test_registered_in_codec_registry():
    assert codec_registry.has("telemetry")
    assert isinstance(codec_registry.create("telemetry"), TelemetryCodec)


def test_decode_full_frame_to_pli_envelope():
    env = TelemetryCodec().decode(_frame())
    assert env.kind == MessageKind.PLI
    assert env.schema_version == SCHEMA_VERSION
    assert env.source_uid == "uav-1"
    assert env.msg_id == "uav-1:1"
    assert env.ts == pytest.approx(1_700_000_000.0)
    assert env.payload["node"] == {"uid": "uav-1", "callsign": "UAV1"}
    assert env.payload["position"]["lat"] == pytest.approx(37.7749)
    assert env.payload["position"]["lon"] == pytest.approx(-122.4194)
    assert env.payload["position"]["hae"] == pytest.approx(100.0)


def test_decode_uses_defaults_for_optional_fields():
    data = json.dumps({"src": "uav-2", "msg_id": "m", "ts": 1.0, "lat": 0.0, "lon": 0.0}).encode(
        "utf-8"
    )
    env = TelemetryCodec().decode(data)
    assert env.payload["node"]["callsign"] == "uav-2"  # falls back to src
    assert env.payload["position"]["hae"] == pytest.approx(0.0)


def test_encode_then_decode_roundtrips():
    codec = TelemetryCodec()
    env = codec.decode(_frame())
    again = codec.decode(codec.encode(env))
    assert again.payload["position"]["lat"] == pytest.approx(37.7749)
    assert again.source_uid == "uav-1"
    assert again.payload["node"]["callsign"] == "UAV1"


def test_encode_chat_envelope_without_position_uses_zero():
    env = Envelope(
        schema_version=SCHEMA_VERSION,
        msg_id="c1",
        ts=1.0,
        source_uid="op",
        kind=MessageKind.CHAT,
        payload={"text": "hi"},
    )
    frame = json.loads(TelemetryCodec().encode(env))
    assert frame["lat"] == 0.0 and frame["lon"] == 0.0 and frame["hae"] == 0.0
    assert frame["callsign"] == "op"


def test_decode_malformed_json_raises():
    with pytest.raises(MeshSAError):
        TelemetryCodec().decode(b"not json {")


def test_decode_non_object_raises():
    with pytest.raises(MeshSAError):
        TelemetryCodec().decode(b"[1, 2, 3]")


def test_decode_missing_required_key_raises():
    data = json.dumps({"src": "x", "msg_id": "m", "ts": 1.0, "lat": 1.0}).encode("utf-8")
    with pytest.raises(MeshSAError):
        TelemetryCodec().decode(data)  # missing 'lon'


def test_decode_out_of_range_lat_raises():
    with pytest.raises(MeshSAError):
        TelemetryCodec().decode(_frame(lat=200.0))  # ValueError from Position validator


def test_decode_non_numeric_position_raises():
    with pytest.raises(MeshSAError):
        TelemetryCodec().decode(_frame(lat=None))  # TypeError from float(None)


def test_decode_out_of_range_battery_pct_raises_meshsaerror():
    # An out-of-range battery_pct fails Telemetry's field validator, raising a
    # pydantic ValidationError; the codec must wrap it as MeshSAError, not leak it.
    frame = _frame(telemetry={"battery_pct": 150})
    with pytest.raises(MeshSAError, match="invalid telemetry frame"):
        TelemetryCodec().decode(frame)


def test_decode_out_of_range_course_raises_meshsaerror():
    # course_deg out of range fails Position's validator (ValidationError); the
    # codec must surface it as MeshSAError rather than a raw ValidationError.
    frame = _frame(course_deg=400.0)
    with pytest.raises(MeshSAError, match="invalid telemetry frame"):
        TelemetryCodec().decode(frame)


def test_decode_carries_course_and_speed():
    env = TelemetryCodec().decode(_frame(course_deg=270.0, speed_ms=8.5))
    assert env.payload["position"]["course_deg"] == pytest.approx(270.0)
    assert env.payload["position"]["speed_ms"] == pytest.approx(8.5)


def test_decode_omits_course_speed_when_absent():
    env = TelemetryCodec().decode(_frame())
    assert "course_deg" not in env.payload["position"]
    assert "speed_ms" not in env.payload["position"]


def test_decode_carries_telemetry_block():
    env = TelemetryCodec().decode(
        _frame(
            telemetry={
                "battery_v": 11.1,
                "battery_pct": 75,
                "current_a": 4.2,
                "attitude": {"roll_deg": 1.0, "pitch_deg": -2.0, "yaw_deg": 90.0},
            }
        )
    )
    tel = env.payload["telemetry"]
    assert tel["battery_v"] == pytest.approx(11.1)
    assert tel["battery_pct"] == 75
    assert tel["current_a"] == pytest.approx(4.2)
    assert tel["attitude"]["yaw_deg"] == pytest.approx(90.0)


def test_decode_omits_telemetry_block_when_absent():
    env = TelemetryCodec().decode(_frame())
    assert "telemetry" not in env.payload


def test_decode_drops_empty_telemetry_block():
    # A present-but-all-None telemetry block collapses to {} and is dropped.
    env = TelemetryCodec().decode(_frame(telemetry={}))
    assert "telemetry" not in env.payload


def test_encode_drops_empty_telemetry_block():
    env = Envelope(
        schema_version=SCHEMA_VERSION,
        msg_id="m",
        ts=1.0,
        source_uid="uav-1",
        kind=MessageKind.PLI,
        payload={
            "node": {"uid": "uav-1", "callsign": "UAV1"},
            "position": {"lat": 1.0, "lon": 2.0, "hae": 0.0},
            "telemetry": {},  # present but empty -> dropped on the wire
        },
    )
    frame = json.loads(TelemetryCodec().encode(env))
    assert "telemetry" not in frame


def test_encode_roundtrips_course_speed_and_telemetry():
    codec = TelemetryCodec()
    src = _frame(
        course_deg=123.0,
        speed_ms=9.0,
        telemetry={"battery_pct": 60, "attitude": {"yaw_deg": 45.0}},
    )
    env = codec.decode(src)
    again = codec.decode(codec.encode(env))
    assert again.payload["position"]["course_deg"] == pytest.approx(123.0)
    assert again.payload["position"]["speed_ms"] == pytest.approx(9.0)
    assert again.payload["telemetry"]["battery_pct"] == 60
    assert again.payload["telemetry"]["attitude"]["yaw_deg"] == pytest.approx(45.0)


def test_encode_omits_telemetry_block_when_absent():
    codec = TelemetryCodec()
    frame = json.loads(codec.encode(codec.decode(_frame())))
    assert "telemetry" not in frame
    assert "course_deg" not in frame
    assert "speed_ms" not in frame
