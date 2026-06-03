"""Property-based codec round-trips (Hypothesis): catch edge cases unit tests miss."""

from hypothesis import given, settings
from hypothesis import strategies as st

from meshsa import CompactCodec, Envelope, JsonCodec, MessageKind

# Conservative strategies: ASCII-ish identifiers <=255 UTF-8 bytes (compact str cap),
# finite coordinates within Position's validated ranges.
_ident = st.text(alphabet=st.characters(min_codepoint=32, max_codepoint=126), max_size=40)
_lat = st.floats(min_value=-90, max_value=90, allow_nan=False, allow_infinity=False)
_lon = st.floats(min_value=-180, max_value=180, allow_nan=False, allow_infinity=False)
_alt = st.floats(min_value=-1000, max_value=10000, allow_nan=False, allow_infinity=False)


def _pli(msg_id, uid, callsign, lat, lon, hae):
    return Envelope(
        schema_version=1,
        msg_id=msg_id,
        ts=1_700_000_000.0,
        source_uid=uid,
        kind=MessageKind.PLI,
        payload={
            "node": {"uid": uid, "callsign": callsign, "tier": "user"},
            "position": {"lat": lat, "lon": lon, "hae": hae, "ce": 10.0, "le": 10.0},
        },
    )


@settings(max_examples=75)
@given(_ident, _ident, _ident, _lat, _lon, _alt)
def test_json_roundtrip_is_lossless(msg_id, uid, callsign, lat, lon, hae):
    env = _pli(msg_id or "m", uid or "u", callsign or "c", lat, lon, hae)
    out = JsonCodec().decode(JsonCodec().encode(env))
    assert out.msg_id == env.msg_id
    assert out.source_uid == env.source_uid
    assert out.kind == env.kind
    assert out.payload == env.payload


@settings(max_examples=75)
@given(_ident, _ident, _lat, _lon)
def test_compact_pli_within_scale_tolerance(msg_id, uid, lat, lon):
    env = _pli(msg_id or "m", uid or "u", uid or "u", lat, lon, 0.0)
    out = CompactCodec().decode(CompactCodec().encode(env))
    # lat/lon are scaled int32 e7 (~1.1cm); allow for rounding.
    assert abs(out.payload["position"]["lat"] - lat) < 1e-6
    assert abs(out.payload["position"]["lon"] - lon) < 1e-6


@settings(max_examples=75)
@given(st.text(alphabet=st.characters(min_codepoint=32, max_codepoint=126), max_size=200))
def test_compact_chat_preserves_text(text):
    env = Envelope(
        schema_version=1,
        msg_id="m",
        ts=1.0,
        source_uid="u",
        kind=MessageKind.CHAT,
        payload={"text": text, "to": None},
    )
    out = CompactCodec().decode(CompactCodec().encode(env))
    assert out.payload["text"] == text
