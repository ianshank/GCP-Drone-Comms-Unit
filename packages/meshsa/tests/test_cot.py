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


def test_pli_remarks_encoded_and_roundtrip():
    env = _pli()
    env.payload["remarks"] = "VBAT 11.8V RSSI 1023"
    c = CotCodec()
    xml = c.encode(env).decode()
    assert "<remarks>VBAT 11.8V RSSI 1023</remarks>" in xml
    out = c.decode(xml.encode())
    assert out.payload["remarks"] == "VBAT 11.8V RSSI 1023"


def test_pli_without_remarks_has_no_remarks_element():
    xml = CotCodec().encode(_pli()).decode()
    assert "<remarks" not in xml
    assert "remarks" not in CotCodec().decode(xml.encode()).payload


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
