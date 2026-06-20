"""Cursor-on-Target (CoT) codec — lets the framework speak directly to ATAK,
WinTAK/iTAK, and FreeTAKServer.

Maps our :class:`Envelope` to/from CoT XML events. PLI envelopes become position
tracks; CHAT envelopes become GeoChat events. All CoT-specific values (event
types, ``how``, stale window) are constructor parameters — nothing is hard-coded.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any

import structlog
from pydantic import ValidationError

from .errors import MeshSAError
from .models import UNKNOWN_ERROR_M, Envelope, MessageKind, Position, Telemetry
from .registry import codec_registry
from .version import SCHEMA_VERSION

_log = structlog.get_logger("meshsa.cot")


def _iso(ts: float) -> str:
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _parse_ts(iso: str) -> float:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


class CotCodec:
    name = "cot"
    # Schema-agnostic: CoT XML carries no meshsa wire schema, so there is no
    # supported_schemas gate; decode always stamps the current SCHEMA_VERSION.

    def __init__(
        self,
        *,
        stale_s: float = 120.0,
        how: str = "m-g",
        pli_type: str = "a-f-G-U-C",
        chat_type: str = "b-t-f",
        cot_version: str = "2.0",
        track_element: str = "track",
        status_element: str = "status",
        attitude_element: str = "attitude",
        battery_attr: str = "battery",
        vendor_element: str = "_meshsa",
        emit_detail: bool = True,
        **_: object,
    ) -> None:
        self.stale_s = stale_s
        self.how = how
        self.pli_type = pli_type
        self.chat_type = chat_type
        self.cot_version = cot_version
        # Richer-track element/attr names are config (no magic strings); a peer can
        # rename them. ``emit_detail`` gates the additive children entirely.
        self.track_element = track_element
        self.status_element = status_element
        self.attitude_element = attitude_element
        self.battery_attr = battery_attr
        self.vendor_element = vendor_element
        self.emit_detail = emit_detail

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
            ce=str(pos.get("ce", UNKNOWN_ERROR_M)),
            le=str(pos.get("le", UNKNOWN_ERROR_M)),
        )
        detail = ET.SubElement(ev, "detail")
        ET.SubElement(detail, "contact", callsign=str(node.get("callsign", env.source_uid)))
        ET.SubElement(detail, "__group", name=str(node.get("tier", "")), role="Team Member")
        if self.emit_detail:
            self._emit_richer_detail(detail, pos, env.payload.get("telemetry") or {})
        return ET.tostring(ev)

    def _emit_richer_detail(
        self, detail: ET.Element, pos: dict[str, Any], telemetry: dict[str, Any]
    ) -> None:
        """Append the additive (M3.1) track/status/vendor/attitude children.

        Every child is guarded: only emitted when its source data are present, so
        a plain PLI yields no richer detail and old readers ignore what they do
        not recognise.
        """
        course = pos.get("course_deg")
        speed = pos.get("speed_ms")
        if course is not None and speed is not None:
            ET.SubElement(detail, self.track_element, course=str(course), speed=str(speed))

        battery_pct = telemetry.get("battery_pct")
        if battery_pct is not None:
            ET.SubElement(detail, self.status_element, {self.battery_attr: str(battery_pct)})

        vendor_attrs: dict[str, str] = {
            attr: str(telemetry[key])
            for attr, key in (("battery_v", "battery_v"), ("current_a", "current_a"))
            if telemetry.get(key) is not None
        }
        if vendor_attrs:
            ET.SubElement(detail, self.vendor_element, vendor_attrs)

        attitude = telemetry.get("attitude") or {}
        att_attrs: dict[str, str] = {
            attr: str(attitude[key])
            for attr, key in (("roll", "roll_deg"), ("pitch", "pitch_deg"), ("yaw", "yaw_deg"))
            if attitude.get(key) is not None
        }
        if att_attrs:
            ET.SubElement(detail, self.attitude_element, att_attrs)

    def _encode_chat(self, env: Envelope) -> bytes:
        text = env.payload.get("text", "")
        ev = self._event(env.msg_id, self.chat_type, env.ts)
        ET.SubElement(
            ev,
            "point",
            lat="0.0",
            lon="0.0",
            hae="0.0",
            ce=str(UNKNOWN_ERROR_M),
            le=str(UNKNOWN_ERROR_M),
        )
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
            raise MeshSAError(f"undecodable CoT ({len(data)} bytes): {exc}") from exc

        detail = ev.find("detail")
        if etype.startswith("b-t-f") or etype.startswith("b.t.f"):
            text = ""
            remarks = detail.find("remarks") if detail is not None else None
            if remarks is not None:
                text = remarks.text or ""
            return Envelope(
                schema_version=SCHEMA_VERSION,
                msg_id=f"{uid}:{ev.attrib.get('time', '')}",
                ts=ts,
                source_uid=uid,
                kind=MessageKind.CHAT,
                payload={"text": text, "to": None},
            )

        pt = ev.find("point")
        pos = {"lat": 0.0, "lon": 0.0, "hae": 0.0, "ce": UNKNOWN_ERROR_M, "le": UNKNOWN_ERROR_M}
        if pt is not None:
            for k in pos:
                if k in pt.attrib:
                    pos[k] = float(pt.attrib[k])
        callsign = uid
        contact = detail.find("contact") if detail is not None else None
        if contact is not None:
            callsign = contact.attrib.get("callsign", uid)
        payload_telemetry: dict[str, Any] = {}
        if detail is not None:
            self._decode_richer_detail(detail, pos, payload_telemetry)
        # Validate the assembled position/telemetry against the model contracts so an
        # untrusted peer cannot inject out-of-range values (course/speed/battery) that
        # bypass the pydantic validators — CoT decode builds dicts directly. Reuses the
        # model validators (DRY) and surfaces violations as MeshSAError, consistent with
        # the telemetry codec's decode.
        try:
            pos = Position.model_validate(pos).model_dump(exclude_none=True)
            if payload_telemetry:
                payload_telemetry = Telemetry.model_validate(payload_telemetry).model_dump(
                    exclude_none=True
                )
        except ValidationError as exc:
            raise MeshSAError(f"invalid CoT track values: {exc}") from exc
        # Symmetric with encode (which stamps ``self.pli_type``): a configured
        # PLI type is always classified as PLI even if it doesn't start with
        # ``a-``; the ``a-`` prefix stays as a backward-compatible fallback.
        kind = (
            MessageKind.PLI
            if etype == self.pli_type or etype.startswith("a-")
            else MessageKind.MARKER
        )
        payload: dict[str, Any] = {
            "node": {"uid": uid, "callsign": callsign},
            "position": pos,
        }
        if payload_telemetry:
            payload["telemetry"] = payload_telemetry
        return Envelope(
            schema_version=SCHEMA_VERSION,
            msg_id=f"{uid}:{ev.attrib.get('time', '')}",
            ts=ts,
            source_uid=uid,
            kind=kind,
            payload=payload,
        )

    def _decode_richer_detail(
        self,
        detail: ET.Element,
        pos: dict[str, Any],
        telemetry: dict[str, Any],
    ) -> None:
        """Parse the additive (M3.1) detail children back, lossless, ignoring
        any unknown children. Mutates ``pos`` and ``telemetry`` in place.

        Numeric attributes come from untrusted peers, so every ``float``/``int``
        parse is guarded: a malformed value (e.g. ``course="invalid"``) is
        surfaced as a :class:`MeshSAError` rather than escaping as a raw
        ``ValueError``/``TypeError``.
        """
        try:
            track = detail.find(self.track_element)
            if track is not None:
                if "course" in track.attrib:
                    pos["course_deg"] = float(track.attrib["course"])
                if "speed" in track.attrib:
                    pos["speed_ms"] = float(track.attrib["speed"])

            status = detail.find(self.status_element)
            if status is not None and self.battery_attr in status.attrib:
                # via float() so a peer sending a float string (e.g. "75.0")
                # is accepted, not rejected by int("75.0").
                telemetry["battery_pct"] = int(float(status.attrib[self.battery_attr]))

            vendor = detail.find(self.vendor_element)
            if vendor is not None:
                for key in ("battery_v", "current_a"):
                    if key in vendor.attrib:
                        telemetry[key] = float(vendor.attrib[key])

            attitude = detail.find(self.attitude_element)
            if attitude is not None:
                att: dict[str, float] = {
                    model_key: float(attitude.attrib[xml_attr])
                    for xml_attr, model_key in (
                        ("roll", "roll_deg"),
                        ("pitch", "pitch_deg"),
                        ("yaw", "yaw_deg"),
                    )
                    if xml_attr in attitude.attrib
                }
                if att:
                    telemetry["attitude"] = att
        except (TypeError, ValueError) as exc:
            _log.debug(
                "malformed richer detail in CoT",
                detail=ET.tostring(detail, encoding="unicode"),
                error=str(exc),
            )
            raise MeshSAError(f"invalid richer detail in CoT: {exc}") from exc


@codec_registry.register("cot")
def _make_cot(**kwargs: Any) -> CotCodec:
    return CotCodec(**kwargs)
