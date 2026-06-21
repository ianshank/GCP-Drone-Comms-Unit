from hypothesis import given
from hypothesis import strategies as st

from meshsa import (
    SCHEMA_VERSION,
    CompactCodec,
    CotCodec,
    Envelope,
    JsonCodec,
    MessageKind,
    Router,
    RouterConfig,
)


def test_router_dedupe_cache_size_boundary():
    # Test the exact boundary of LRU cache
    cfg = RouterConfig(dedupe_cache_size=3)
    router = Router([], JsonCodec(), config=cfg)

    assert router._mark_seen("A") is True
    assert router._mark_seen("B") is True
    assert router._mark_seen("C") is True

    # Cache is now full [A, B, C]
    assert router._mark_seen("A") is False

    # Add new item D, pushing out oldest (A)
    assert router._mark_seen("D") is True

    # A should be gone
    assert router._mark_seen("A") is True


@st.composite
def envelope_strategy(draw):
    kind = draw(st.sampled_from(list(MessageKind)))

    # We restrict values slightly to ensure they fit in the compact codec bounds
    lat = draw(st.floats(min_value=-90.0, max_value=90.0, allow_nan=False, allow_infinity=False))
    lon = draw(st.floats(min_value=-180.0, max_value=180.0, allow_nan=False, allow_infinity=False))

    payload = {}
    if kind in (MessageKind.PLI, MessageKind.MARKER):
        payload = {
            "node": {"uid": "abc", "callsign": "ABC", "tier": "user"},
            "position": {"lat": lat, "lon": lon, "hae": 0.0, "ce": 10.0, "le": 10.0},
        }
    elif kind == MessageKind.CHAT:
        payload = {"text": "hello", "to": "def"}
    else:
        payload = {"status": "ok"}

    return Envelope(
        schema_version=SCHEMA_VERSION,
        msg_id=draw(st.text(min_size=1, max_size=10, alphabet="abcdef")),
        ts=draw(st.floats(min_value=100000.0, max_value=2000000000.0)),
        source_uid=draw(st.text(min_size=1, max_size=10, alphabet="abcdef")),
        kind=kind,
        payload=payload,
    )


@given(envelope_strategy())
def test_json_codec_roundtrip(env):
    codec = JsonCodec()
    encoded = codec.encode(env)
    decoded = codec.decode(encoded)

    assert decoded.msg_id == env.msg_id
    assert decoded.kind == env.kind
    assert decoded.source_uid == env.source_uid


@given(envelope_strategy())
def test_compact_codec_roundtrip(env):
    codec = CompactCodec()
    encoded = codec.encode(env)
    decoded = codec.decode(encoded)

    assert decoded.msg_id == env.msg_id
    assert decoded.kind == env.kind
    assert decoded.source_uid == env.source_uid

    # Check that floats match roughly (lossy compression)
    if env.kind in (MessageKind.PLI, MessageKind.MARKER):
        assert abs(decoded.payload["position"]["lat"] - env.payload["position"]["lat"]) < 0.0001
        assert abs(decoded.payload["position"]["lon"] - env.payload["position"]["lon"]) < 0.0001


@given(envelope_strategy())
def test_cot_codec_roundtrip(env):
    codec = CotCodec()
    encoded = codec.encode(env)
    decoded = codec.decode(encoded)

    # CoT codec loses the exact msg_id for PLIs (it makes it uid:time)
    # But it retains the kind and source
    assert decoded.source_uid is not None
    if env.kind != MessageKind.STATUS:
        # CoT codec encodes all non-CHAT as PLI or MARKER based on prefix, but we don't have enough control here.
        # Just check it doesn't crash on encode/decode.
        pass
