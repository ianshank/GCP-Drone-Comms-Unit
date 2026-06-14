import pytest

from meshsa import CotCodec, Envelope, MeshSAError, MessageKind, codec_registry


def _pli(mid="m1", ts=1_700_000_000.0):
    return Envelope(
        msg_id=mid,
        ts=ts,
        source_uid="user-1",
        kind=MessageKind.PLI,
        payload={
            "node": {"callsign": "FOX1", "tier": "user"},
            "position": {"lat": 37.5, "lon": -122.3, "hae": 12.0},
        },
    )


def test_cot_registered():
    assert codec_registry.has("cot")
    assert isinstance(codec_registry.create("cot"), CotCodec)


def test_pli_encodes_atak_fields():
    xml = CotCodec().encode(_pli()).decode()
    assert 'uid="user-1"' in xml and 'type="a-f-G-U-C"' in xml
    assert 'lat="37.5"' in xml and 'lon="-122.3"' in xml
    assert 'callsign="FOX1"' in xml
    assert "<stale" not in xml and "stale=" in xml  # stale is an attribute


def test_pli_roundtrip_semantic():
    c = CotCodec()
    out = c.decode(c.encode(_pli()))
    assert out.kind == MessageKind.PLI
    assert out.source_uid == "user-1"
    assert out.payload["position"]["lat"] == 37.5
    assert out.payload["node"]["callsign"] == "FOX1"


def test_chat_roundtrip():
    c = CotCodec()
    env = Envelope(
        msg_id="c1",
        ts=1_700_000_000.0,
        source_uid="user-1",
        kind=MessageKind.CHAT,
        payload={"text": "rally point alpha", "to": None},
    )
    xml = c.encode(env).decode()
    assert 'type="b-t-f"' in xml and "rally point alpha" in xml
    back = c.decode(xml.encode())
    assert back.kind == MessageKind.CHAT
    assert back.payload["text"] == "rally point alpha"


def test_marker_type_maps_to_marker():
    marker = b'<event version="2.0" uid="x" type="u-d-p" time="2023-11-14T22:13:20.000Z"><point lat="1" lon="2"/></event>'
    out = CotCodec().decode(marker)
    assert out.kind == MessageKind.MARKER
    assert out.payload["position"]["lat"] == 1.0


def test_custom_types_not_hardcoded():
    c = CotCodec(pli_type="a-f-A-M-F-Q", stale_s=30.0)
    assert 'type="a-f-A-M-F-Q"' in c.encode(_pli()).decode()


def test_bad_cot_raises():
    with pytest.raises(MeshSAError):
        CotCodec().decode(b"<notevent/>")
    with pytest.raises(MeshSAError):
        CotCodec().decode(b"<<<")


def test_pli_without_detail_falls_back_to_uid():
    xml = (
        b'<event version="2.0" uid="z" type="a-f-G-U-C" '
        b'time="2023-11-14T22:13:20.000Z"><point lat="5" lon="6"/></event>'
    )
    out = CotCodec().decode(xml)
    assert out.payload["node"]["callsign"] == "z"


def test_chat_without_remarks_yields_empty_text():
    xml = (
        b'<event version="2.0" uid="z" type="b-t-f" '
        b'time="2023-11-14T22:13:20.000Z"><point lat="0" lon="0"/></event>'
    )
    out = CotCodec().decode(xml)
    assert out.payload["text"] == ""


def test_pli_with_detail_but_no_contact():
    xml = (
        b'<event version="2.0" uid="z" type="a-f-G-U-C" '
        b'time="2023-11-14T22:13:20.000Z"><point lat="5" lon="6"/>'
        b"<detail><remarks>note</remarks></detail></event>"
    )
    out = CotCodec().decode(xml)
    assert out.payload["node"]["callsign"] == "z"


def test_decode_without_point_uses_zero_position():
    xml = (
        b'<event version="2.0" uid="z" type="a-f-G-U-C" '
        b'time="2023-11-14T22:13:20.000Z">'
        b'<detail><contact callsign="QRU"/></detail></event>'
    )
    out = CotCodec().decode(xml)
    assert out.payload["position"]["lat"] == 0.0
    assert out.payload["node"]["callsign"] == "QRU"


def _rich_pli(mid="m1", ts=1_700_000_000.0):
    return Envelope(
        msg_id=mid,
        ts=ts,
        source_uid="uav-1",
        kind=MessageKind.PLI,
        payload={
            "node": {"callsign": "UAV1", "tier": "user"},
            "position": {
                "lat": 37.5,
                "lon": -122.3,
                "hae": 12.0,
                "course_deg": 270.0,
                "speed_ms": 8.5,
            },
            "telemetry": {
                "battery_v": 11.1,
                "battery_pct": 75,
                "current_a": 4.2,
                "attitude": {"roll_deg": 1.0, "pitch_deg": -2.0, "yaw_deg": 90.0},
            },
        },
    )


def test_pli_emits_track_status_attitude_detail():
    xml = CotCodec().encode(_rich_pli()).decode()
    assert '<track course="270.0" speed="8.5"' in xml
    assert 'battery="75"' in xml and "<status" in xml
    assert 'battery_v="11.1"' in xml and 'current_a="4.2"' in xml
    assert "<_meshsa" in xml
    assert 'roll="1.0"' in xml and 'pitch="-2.0"' in xml and 'yaw="90.0"' in xml
    assert "<attitude" in xml


def test_pli_rich_roundtrips_track_status_attitude():
    c = CotCodec()
    out = c.decode(c.encode(_rich_pli()))
    pos = out.payload["position"]
    assert pos["course_deg"] == 270.0 and pos["speed_ms"] == 8.5
    tel = out.payload["telemetry"]
    assert tel["battery_pct"] == 75
    assert tel["battery_v"] == 11.1 and tel["current_a"] == 4.2
    assert tel["attitude"] == {"roll_deg": 1.0, "pitch_deg": -2.0, "yaw_deg": 90.0}


def test_plain_pli_encode_has_no_richer_detail():
    # A plain PLI (no course/speed/telemetry) must emit NO richer detail children.
    xml = CotCodec().encode(_pli()).decode()
    assert "<track" not in xml
    assert "<status" not in xml
    assert "<_meshsa" not in xml
    assert "<attitude" not in xml


def test_track_omitted_when_only_one_of_course_speed():
    env = _pli()
    env.payload["position"]["course_deg"] = 90.0  # speed absent
    xml = CotCodec().encode(env).decode()
    assert "<track" not in xml


def test_emit_detail_false_suppresses_richer_children():
    xml = CotCodec(emit_detail=False).encode(_rich_pli()).decode()
    assert "<track" not in xml
    assert "<status" not in xml
    assert "<attitude" not in xml
    # base contact/group detail is still present
    assert "callsign=" in xml


def test_decode_ignores_unknown_detail_children():
    xml = (
        b'<event version="2.0" uid="z" type="a-f-G-U-C" '
        b'time="2023-11-14T22:13:20.000Z"><point lat="5" lon="6"/>'
        b'<detail><contact callsign="QRU"/>'
        b'<unknownchild foo="bar"/><track course="10.0" speed="2.0"/>'
        b"</detail></event>"
    )
    out = CotCodec().decode(xml)
    assert out.payload["node"]["callsign"] == "QRU"
    assert out.payload["position"]["course_deg"] == 10.0
    assert out.payload["position"]["speed_ms"] == 2.0


def test_decode_track_with_only_course_or_only_speed():
    course_only = (
        b'<event version="2.0" uid="z" type="a-f-G-U-C" '
        b'time="2023-11-14T22:13:20.000Z"><point lat="5" lon="6"/>'
        b'<detail><track course="30.0"/></detail></event>'
    )
    out = CotCodec().decode(course_only)
    assert out.payload["position"]["course_deg"] == 30.0
    assert "speed_ms" not in out.payload["position"]

    speed_only = (
        b'<event version="2.0" uid="z" type="a-f-G-U-C" '
        b'time="2023-11-14T22:13:20.000Z"><point lat="5" lon="6"/>'
        b'<detail><track speed="4.0"/></detail></event>'
    )
    out = CotCodec().decode(speed_only)
    assert out.payload["position"]["speed_ms"] == 4.0
    assert "course_deg" not in out.payload["position"]


def test_decode_vendor_with_only_one_attr():
    xml = (
        b'<event version="2.0" uid="z" type="a-f-G-U-C" '
        b'time="2023-11-14T22:13:20.000Z"><point lat="5" lon="6"/>'
        b'<detail><_meshsa battery_v="12.0"/></detail></event>'
    )
    out = CotCodec().decode(xml)
    tel = out.payload["telemetry"]
    assert tel == {"battery_v": 12.0}


def test_decode_empty_attitude_element_yields_no_attitude():
    xml = (
        b'<event version="2.0" uid="z" type="a-f-G-U-C" '
        b'time="2023-11-14T22:13:20.000Z"><point lat="5" lon="6"/>'
        b"<detail><attitude/></detail></event>"
    )
    out = CotCodec().decode(xml)
    assert "telemetry" not in out.payload


def test_decode_partial_attitude_and_status():
    xml = (
        b'<event version="2.0" uid="z" type="a-f-G-U-C" '
        b'time="2023-11-14T22:13:20.000Z"><point lat="5" lon="6"/>'
        b'<detail><status battery="40"/>'
        b'<attitude yaw="180.0"/></detail></event>'
    )
    out = CotCodec().decode(xml)
    tel = out.payload["telemetry"]
    assert tel["battery_pct"] == 40
    assert tel["attitude"] == {"yaw_deg": 180.0}
    assert "course_deg" not in out.payload["position"]


@pytest.mark.parametrize(
    "detail",
    [
        b'<track course="invalid" speed="3.0"/>',
        b'<status battery="full"/>',
        b'<_meshsa battery_v="low"/>',
        b'<attitude roll="tilt"/>',
    ],
)
def test_decode_nonnumeric_richer_detail_raises_meshsaerror(detail):
    # A peer sending a non-numeric richer-detail attribute must surface as a
    # MeshSAError, never a raw ValueError/TypeError escaping the decoder.
    xml = (
        b'<event version="2.0" uid="z" type="a-f-G-U-C" '
        b'time="2023-11-14T22:13:20.000Z"><point lat="5" lon="6"/>'
        b"<detail>" + detail + b"</detail></event>"
    )
    with pytest.raises(MeshSAError, match="invalid richer detail in CoT"):
        CotCodec().decode(xml)


@pytest.mark.parametrize(
    "detail",
    [
        b'<track course="400" speed="3.0"/>',  # course out of [0, 360)
        b'<track course="10" speed="-5"/>',  # speed must be >= 0
        b'<status battery="150"/>',  # battery_pct out of [0, 100]
        b'<_meshsa battery_v="-1"/>',  # battery_v must be >= 0
    ],
)
def test_decode_out_of_range_richer_detail_raises_meshsaerror(detail):
    # Numeric-but-out-of-contract values from a peer must be rejected with the same
    # bounds the Position/Telemetry validators enforce (CoT builds dicts directly),
    # surfaced as MeshSAError rather than producing an out-of-contract envelope.
    xml = (
        b'<event version="2.0" uid="z" type="a-f-G-U-C" '
        b'time="2023-11-14T22:13:20.000Z"><point lat="5" lon="6"/>'
        b"<detail>" + detail + b"</detail></event>"
    )
    with pytest.raises(MeshSAError, match="invalid CoT track values"):
        CotCodec().decode(xml)


def test_cot_sentinel_matches_position_default():
    # The CoT "unknown error" sentinel and the Position ce/le default must stay
    # in lockstep via the shared UNKNOWN_ERROR_M constant.
    from meshsa import Position
    from meshsa.models import UNKNOWN_ERROR_M

    assert Position(lat=0.0, lon=0.0).ce == UNKNOWN_ERROR_M
    chat = Envelope(
        msg_id="m",
        ts=1.0,
        source_uid="u",
        kind=MessageKind.CHAT,
        payload={"text": "hi", "to": None},
    )
    xml = CotCodec().encode(chat).decode()
    assert f'ce="{UNKNOWN_ERROR_M}"' in xml
