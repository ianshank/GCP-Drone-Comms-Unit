import pytest

from meshsa import CompactCodec, Envelope, JsonCodec, MeshSAError, MessageKind, codec_registry
from meshsa.errors import IncompatibleSchemaError
from meshsa.version import SCHEMA_VERSION


def _pli(ce=9999999.0):
    return Envelope(
        msg_id="id-1",
        ts=1_700_000_000.0,
        source_uid="user-1",
        kind=MessageKind.PLI,
        payload={
            "node": {"callsign": "FOX1", "tier": "backbone"},
            "position": {"lat": 37.5, "lon": -122.3, "hae": 12.0, "ce": ce, "le": ce},
        },
    )


def test_registered():
    assert codec_registry.has("compact")
    assert isinstance(codec_registry.create("compact"), CompactCodec)


def test_pli_fits_lora_and_is_far_smaller_than_json():
    c = CompactCodec()
    assert len(c.encode(_pli())) <= 237  # single Meshtastic packet
    assert len(c.encode(_pli())) < len(JsonCodec().encode(_pli())) // 3


def test_pli_roundtrip_precision_and_clamp():
    out = CompactCodec().decode(CompactCodec().encode(_pli()))
    assert out.kind == MessageKind.PLI
    assert out.source_uid == "user-1"
    assert abs(out.payload["position"]["lat"] - 37.5) < 1e-6
    assert abs(out.payload["position"]["lon"] - (-122.3)) < 1e-6
    assert out.payload["node"]["callsign"] == "FOX1"
    assert out.payload["node"]["tier"] == "backbone"
    assert out.payload["position"]["ce"] == 65535.0  # clamped


def test_pli_small_ce_preserved():
    out = CompactCodec().decode(CompactCodec().encode(_pli(ce=25.0)))
    assert out.payload["position"]["ce"] == 25.0


def test_chat_roundtrip_with_and_without_to():
    c = CompactCodec()
    a = Envelope(
        msg_id="c1",
        ts=1.0,
        source_uid="u",
        kind=MessageKind.CHAT,
        payload={"text": "rally alpha", "to": "team-1"},
    )
    b = Envelope(
        msg_id="c2",
        ts=1.0,
        source_uid="u",
        kind=MessageKind.CHAT,
        payload={"text": "hi", "to": None},
    )
    ra, rb = c.decode(c.encode(a)), c.decode(c.encode(b))
    assert ra.payload == {"text": "rally alpha", "to": "team-1"}
    assert rb.payload == {"text": "hi", "to": None}


def test_marker_uses_position_body():
    c = CompactCodec()
    e = Envelope(
        msg_id="m",
        ts=1.0,
        source_uid="u",
        kind=MessageKind.MARKER,
        payload={"node": {"callsign": "X"}, "position": {"lat": 1.0, "lon": 2.0}},
    )
    out = c.decode(c.encode(e))
    assert out.kind == MessageKind.MARKER
    assert abs(out.payload["position"]["lat"] - 1.0) < 1e-6


def test_status_falls_back_to_json_body():
    c = CompactCodec()
    e = Envelope(
        msg_id="s",
        ts=1.0,
        source_uid="u",
        kind=MessageKind.STATUS,
        payload={"battery": 88, "mode": "scan"},
    )
    out = c.decode(c.encode(e))
    assert out.kind == MessageKind.STATUS
    assert out.payload == {"battery": 88, "mode": "scan"}


def test_unknown_tier_defaults_to_zero():
    c = CompactCodec()
    e = Envelope(
        msg_id="m",
        ts=1.0,
        source_uid="u",
        kind=MessageKind.PLI,
        payload={"node": {"callsign": "X", "tier": "bogus"}, "position": {"lat": 0.0, "lon": 0.0}},
    )
    out = c.decode(c.encode(e))
    assert out.payload["node"]["tier"] == "user"  # index 0 fallback


def test_string_too_long_raises():
    e = Envelope(
        msg_id="x" * 300,
        ts=1.0,
        source_uid="u",
        kind=MessageKind.PLI,
        payload={"node": {"callsign": "X"}, "position": {"lat": 0, "lon": 0}},
    )
    with pytest.raises(MeshSAError):
        CompactCodec().encode(e)


def test_incompatible_schema_rejected():
    bad = Envelope(
        schema_version=SCHEMA_VERSION + 9,
        msg_id="m",
        ts=1.0,
        source_uid="u",
        kind=MessageKind.PLI,
        payload={"node": {"callsign": "X"}, "position": {"lat": 0, "lon": 0}},
    )
    with pytest.raises(IncompatibleSchemaError):
        CompactCodec().decode(CompactCodec().encode(bad))


def test_garbage_rejected():
    with pytest.raises(MeshSAError):
        CompactCodec().decode(b"\x01")  # truncated


def test_negative_error_estimate_clamped_to_zero():
    e = Envelope(
        msg_id="m",
        ts=1.0,
        source_uid="u",
        kind=MessageKind.PLI,
        payload={
            "node": {"callsign": "X"},
            "position": {"lat": 0.0, "lon": 0.0, "ce": -5.0, "le": -1.0},
        },
    )
    out = CompactCodec().decode(CompactCodec().encode(e))
    assert out.payload["position"]["ce"] == 0.0
    assert out.payload["position"]["le"] == 0.0
