"""Property-based codec round-trips (Hypothesis): catch edge cases unit tests miss."""

from hypothesis import given, settings
from hypothesis import strategies as st

from meshsa import CompactCodec, CotCodec, Envelope, JsonCodec, MessageKind

# Conservative strategies: ASCII-ish identifiers <=255 UTF-8 bytes (compact str cap),
# finite coordinates within Position's validated ranges.
_ident = st.text(alphabet=st.characters(min_codepoint=32, max_codepoint=126), max_size=40)
_lat = st.floats(min_value=-90, max_value=90, allow_nan=False, allow_infinity=False)
_lon = st.floats(min_value=-180, max_value=180, allow_nan=False, allow_infinity=False)
_alt = st.floats(min_value=-1000, max_value=10000, allow_nan=False, allow_infinity=False)
# Optional richer-track fields (M3.1): None | in-range value.
_course = st.one_of(
    st.none(), st.floats(min_value=0, max_value=359.999, allow_nan=False, allow_infinity=False)
)
_speed = st.one_of(
    st.none(), st.floats(min_value=0, max_value=400, allow_nan=False, allow_infinity=False)
)


def _pli(msg_id, uid, callsign, lat, lon, hae, course=None, speed=None):
    position = {"lat": lat, "lon": lon, "hae": hae, "ce": 10.0, "le": 10.0}
    # Mirror the wire contract: absent (None) richer keys never enter the payload.
    if course is not None:
        position["course_deg"] = course
    if speed is not None:
        position["speed_ms"] = speed
    return Envelope(
        schema_version=1,
        msg_id=msg_id,
        ts=1_700_000_000.0,
        source_uid=uid,
        kind=MessageKind.PLI,
        payload={
            "node": {"uid": uid, "callsign": callsign, "tier": "user"},
            "position": position,
        },
    )


@settings(max_examples=75)
@given(_ident, _ident, _ident, _lat, _lon, _alt, _course, _speed)
def test_json_roundtrip_is_lossless(msg_id, uid, callsign, lat, lon, hae, course, speed):
    env = _pli(msg_id or "m", uid or "u", callsign or "c", lat, lon, hae, course, speed)
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


# ── CoT richer detail (M3.1): course/speed, battery, current, attitude round-trip ──
#
# ``CotCodec`` rewrites msg_id (``uid:time``) by design, so the property is over the
# payload: every richer field that was present comes back, and nothing is invented.
# Course and speed are generated together because the ``<track>`` element is only
# emitted when both are present (pinned by ``test_track_omitted_when_only_one_of_course_speed``).

_pct = st.one_of(st.none(), st.integers(min_value=0, max_value=100))
_volts = st.one_of(
    st.none(), st.floats(min_value=0, max_value=60, allow_nan=False, allow_infinity=False)
)
_amps = st.one_of(
    st.none(), st.floats(min_value=-100, max_value=100, allow_nan=False, allow_infinity=False)
)
_angle = st.one_of(
    st.none(), st.floats(min_value=-180, max_value=180, allow_nan=False, allow_infinity=False)
)
_track = st.one_of(
    st.none(),
    st.tuples(
        st.floats(min_value=0, max_value=359.999, allow_nan=False, allow_infinity=False),
        st.floats(min_value=0, max_value=400, allow_nan=False, allow_infinity=False),
    ),
)


def _rich_pli(uid, lat, lon, track, battery_pct, battery_v, current_a, roll, pitch, yaw):
    position = {"lat": lat, "lon": lon, "hae": 0.0, "ce": 10.0, "le": 10.0}
    if track is not None:
        position["course_deg"], position["speed_ms"] = track
    telemetry = {
        k: v
        for k, v in (
            ("battery_pct", battery_pct),
            ("battery_v", battery_v),
            ("current_a", current_a),
        )
        if v is not None
    }
    attitude = {
        k: v
        for k, v in (("roll_deg", roll), ("pitch_deg", pitch), ("yaw_deg", yaw))
        if v is not None
    }
    if attitude:
        telemetry["attitude"] = attitude
    payload = {"node": {"uid": uid, "callsign": uid, "tier": "user"}, "position": position}
    if telemetry:
        payload["telemetry"] = telemetry
    return Envelope(
        schema_version=1,
        msg_id="m",
        ts=1_700_000_000.0,
        source_uid=uid,
        kind=MessageKind.PLI,
        payload=payload,
    )


@settings(max_examples=100)
@given(_ident, _lat, _lon, _track, _pct, _volts, _amps, _angle, _angle, _angle)
def test_cot_rich_pli_roundtrip_is_lossless(
    uid, lat, lon, track, battery_pct, battery_v, current_a, roll, pitch, yaw
):
    env = _rich_pli(
        uid or "u", lat, lon, track, battery_pct, battery_v, current_a, roll, pitch, yaw
    )
    out = CotCodec().decode(CotCodec().encode(env))
    assert out.kind == MessageKind.PLI
    assert out.source_uid == env.source_uid
    assert out.payload["node"]["callsign"] == env.payload["node"]["callsign"]
    assert out.payload["position"] == env.payload["position"]
    assert out.payload.get("telemetry") == env.payload.get("telemetry")


@settings(max_examples=50)
@given(_ident, _lat, _lon, _track, _pct, _volts, _amps, _angle, _angle, _angle)
def test_cot_emit_detail_false_drops_every_richer_field(
    uid, lat, lon, track, battery_pct, battery_v, current_a, roll, pitch, yaw
):
    env = _rich_pli(
        uid or "u", lat, lon, track, battery_pct, battery_v, current_a, roll, pitch, yaw
    )
    out = CotCodec(emit_detail=False).decode(CotCodec(emit_detail=False).encode(env))
    assert "telemetry" not in out.payload
    assert "course_deg" not in out.payload["position"]
    assert "speed_ms" not in out.payload["position"]
