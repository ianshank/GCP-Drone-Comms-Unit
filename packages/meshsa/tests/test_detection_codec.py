"""DetectionCodec: detection JSON frame <-> MARKER Envelope (fakes-only)."""

import json

import pytest

from meshsa import DetectionCodec, MessageKind, codec_registry
from meshsa.errors import MeshSAError


def test_registered_in_codec_registry():
    assert codec_registry.has("detection")
    assert isinstance(codec_registry.create("detection"), DetectionCodec)


def _frame(**over) -> bytes:
    base = {
        "src": "yolo-cam1",
        "msg_id": "d:1",
        "ts": 1_700_000_000.0,
        "lat": 37.0,
        "lon": -122.0,
        "label": "person",
        "confidence": 0.91,
    }
    base.update(over)
    return json.dumps(base).encode("utf-8")


def test_decode_builds_marker_envelope():
    env = DetectionCodec().decode(_frame(track_id=7, ce=25.0, bearing_deg=42.0))
    assert env.kind is MessageKind.MARKER
    assert env.source_uid == "yolo-cam1"
    assert env.payload["position"]["lat"] == 37.0 and env.payload["position"]["ce"] == 25.0
    det = env.payload["detection"]
    assert det == {"label": "person", "confidence": 0.91, "track_id": 7, "bearing_deg": 42.0}
    assert env.payload["node"]["callsign"] == "person"  # defaults to label


def test_callsign_override():
    env = DetectionCodec().decode(_frame(callsign="TGT-1"))
    assert env.payload["node"]["callsign"] == "TGT-1"


def test_missing_required_keys_raise():
    with pytest.raises(MeshSAError, match="missing keys"):
        DetectionCodec().decode(json.dumps({"src": "x"}).encode())


def test_malformed_json_and_non_object_raise():
    with pytest.raises(MeshSAError, match="undecodable"):
        DetectionCodec().decode(b"{not json")
    with pytest.raises(MeshSAError, match="not an object"):
        DetectionCodec().decode(b"[1,2,3]")


def test_out_of_range_values_raise():
    with pytest.raises(MeshSAError, match="invalid detection frame"):
        DetectionCodec().decode(_frame(confidence=1.5))  # confidence > 1
    with pytest.raises(MeshSAError, match="invalid detection frame"):
        DetectionCodec().decode(_frame(lat=200.0))  # lat out of range


def test_encode_roundtrip():
    codec = DetectionCodec()
    env = codec.decode(_frame(track_id=3))
    frame2 = codec.encode(env)
    env2 = codec.decode(frame2)
    assert env2.payload["detection"] == env.payload["detection"]
    assert env2.payload["position"]["lat"] == env.payload["position"]["lat"]


def test_encode_validates_blocks_and_raises_on_invalid():
    from meshsa import Envelope, MessageKind

    # Missing/invalid position+detection -> MeshSAError (no silent 0,0 frame), matching
    # TelemetryCodec.encode's validate-then-raise contract.
    bad = Envelope(msg_id="m", ts=1.0, source_uid="s", kind=MessageKind.MARKER, payload={})
    with pytest.raises(MeshSAError, match="invalid detection envelope"):
        DetectionCodec().encode(bad)
