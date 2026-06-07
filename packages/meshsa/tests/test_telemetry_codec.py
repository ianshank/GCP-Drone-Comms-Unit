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


def test_decode_carries_optional_remarks():
    env = TelemetryCodec().decode(_frame(remarks="VBAT 11.8V RSSI 1023"))
    assert env.payload["remarks"] == "VBAT 11.8V RSSI 1023"
    # remarks lives at the payload root, not inside node/position
    assert env.payload["node"] == {"uid": "uav-1", "callsign": "UAV1"}


def test_decode_without_remarks_omits_key():
    assert "remarks" not in TelemetryCodec().decode(_frame()).payload


def test_remarks_roundtrips():
    codec = TelemetryCodec()
    env = codec.decode(_frame(remarks="CUR 2.5A"))
    again = codec.decode(codec.encode(env))
    assert again.payload["remarks"] == "CUR 2.5A"


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
