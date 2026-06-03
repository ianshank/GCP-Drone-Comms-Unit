"""Cursor-on-Target (CoT) codec — lets the framework speak directly to ATAK,
WinTAK/iTAK, and FreeTAKServer.

Maps our :class:`Envelope` to/from CoT XML events. PLI envelopes become position
tracks; CHAT envelopes become GeoChat events. All CoT-specific values (event
types, ``how``, stale window) are constructor parameters — nothing is hard-coded.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from .errors import MeshSAError
from .models import Envelope, MessageKind
from .registry import codec_registry
from .version import SCHEMA_VERSION


def _iso(ts: float) -> str:
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _parse_ts(iso: str) -> float:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


class CotCodec:
    name = "cot"

    def __init__(
        self,
        *,
        stale_s: float = 120.0,
        how: str = "m-g",
        pli_type: str = "a-f-G-U-C",
        chat_type: str = "b-t-f",
        cot_version: str = "2.0",
        **_: object,
    ) -> None:
        self.stale_s = stale_s
        self.how = how
        self.pli_type = pli_type
        self.chat_type = chat_type
        self.cot_version = cot_version

    # -- encode -------------------------------------------------------------
    def encode(self, envelope: Envelope) -> bytes:
        if envelope.kind == MessageKind.CHAT:
            return self._encode_chat(envelope)
        return self._encode_pli(envelope)

    def _event(self, uid: str, etype: str, ts: float) -> ET.Element:
        ev = ET.Element(
            "event",
            version=self.cot_version,
            uid=uid,
            type=etype,
            how=self.how,
            time=_iso(ts),
            start=_iso(ts),
            stale=_iso(ts + self.stale_s),
        )
        return ev

    def _encode_pli(self, env: Envelope) -> bytes:
        node = env.payload.get("node", {})
        pos = env.payload.get("position", {})
        ev = self._event(env.source_uid, self.pli_type, env.ts)
        ET.SubElement(
            ev,
            "point",
            lat=str(pos.get("lat", 0.0)),
            lon=str(pos.get("lon", 0.0)),
            hae=str(pos.get("hae", 0.0)),
            ce=str(pos.get("ce", 9999999.0)),
            le=str(pos.get("le", 9999999.0)),
        )
        detail = ET.SubElement(ev, "detail")
        ET.SubElement(detail, "contact", callsign=str(node.get("callsign", env.source_uid)))
        ET.SubElement(detail, "__group", name=str(node.get("tier", "")), role="Team Member")
        return ET.tostring(ev)

    def _encode_chat(self, env: Envelope) -> bytes:
        text = env.payload.get("text", "")
        ev = self._event(env.msg_id, self.chat_type, env.ts)
        ET.SubElement(ev, "point", lat="0.0", lon="0.0", hae="0.0", ce="9999999.0", le="9999999.0")
        detail = ET.SubElement(ev, "detail")
        chat = ET.SubElement(
            detail,
            "__chat",
            senderCallsign=env.source_uid,
            id=str(env.payload.get("to") or "All Chat Rooms"),
        )
        ET.SubElement(
            chat, "chatgrp", uid0=env.source_uid, uid1=str(env.payload.get("to") or "All")
        )
        ET.SubElement(detail, "remarks").text = text
        return ET.tostring(ev)

    # -- decode -------------------------------------------------------------
    def decode(self, data: bytes) -> Envelope:
        try:
            ev = ET.fromstring(data)
            if ev.tag != "event":
                raise ValueError("root is not <event>")
            uid = ev.attrib["uid"]
            etype = ev.attrib.get("type", "")
            ts = _parse_ts(ev.attrib.get("time", _iso(0)))
        except Exception as exc:
            raise MeshSAError(f"undecodable CoT: {exc}") from exc

        detail = ev.find("detail")
        if etype.startswith("b-t-f") or etype.startswith("b.t.f"):
            text = ""
            if detail is not None and detail.find("remarks") is not None:
                text = detail.find("remarks").text or ""
            return Envelope(
                schema_version=SCHEMA_VERSION,
                msg_id=f"{uid}:{ev.attrib.get('time', '')}",
                ts=ts,
                source_uid=uid,
                kind=MessageKind.CHAT,
                payload={"text": text, "to": None},
            )

        pt = ev.find("point")
        pos = {"lat": 0.0, "lon": 0.0, "hae": 0.0, "ce": 9999999.0, "le": 9999999.0}
        if pt is not None:
            for k in pos:
                if k in pt.attrib:
                    pos[k] = float(pt.attrib[k])
        callsign = uid
        if detail is not None and detail.find("contact") is not None:
            callsign = detail.find("contact").attrib.get("callsign", uid)
        kind = MessageKind.PLI if etype.startswith("a-") else MessageKind.MARKER
        return Envelope(
            schema_version=SCHEMA_VERSION,
            msg_id=f"{uid}:{ev.attrib.get('time', '')}",
            ts=ts,
            source_uid=uid,
            kind=kind,
            payload={"node": {"uid": uid, "callsign": callsign}, "position": pos},
        )


@codec_registry.register("cot")
def _make_cot(**kwargs: object) -> CotCodec:
    return CotCodec(**kwargs)
