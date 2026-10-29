"""Cursor-on-Target (CoT) codec — lets the framework speak directly to ATAK,
WinTAK/iTAK, and FreeTAKServer.

Maps our :class:`Envelope` to/from CoT XML events. PLI envelopes become position
tracks; CHAT envelopes become GeoChat events; MARKER envelopes become detection points.
All CoT-specific values (event types, ``how``, stale window, element names) are
constructor parameters gathered into :class:`_CotNaming` — nothing is hard-coded.

Layout (code-hygiene-modularity T-4.4): the encode/decode logic is module-level
functions over a frozen :class:`_CotNaming`, one per CoT event shape, and
:class:`CotCodec` is the registry-facing facade that owns the naming and dispatches.
The wire output is byte-identical to the previous class-method layout
(``tests/test_snapshots.py`` pins it).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import structlog
from pydantic import ValidationError

from .defaults import DEFAULT_COT_STALE_S
from .errors import MeshSAError
from .models import UNKNOWN_ERROR_M, Detection, Envelope, MessageKind, Position, Telemetry
from .registry import codec_registry
from .version import SCHEMA_VERSION

_log = structlog.get_logger("meshsa.cot")


def _iso(ts: float) -> str:
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _parse_ts(iso: str) -> float:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


@dataclass(frozen=True)
class _CotNaming:
    """Every CoT-specific name the codec emits or looks for — config, not magic strings."""

    stale_s: float = DEFAULT_COT_STALE_S
    how: str = "m-g"
    pli_type: str = "a-f-G-U-C"
    chat_type: str = "b-t-f"
    #: MARKER (object-detection) CoT type. Default a-u-G = unknown ground (affiliation
    #: unknown), so detections never render as friendly tracks like PLIs do.
    marker_type: str = "a-u-G"
    cot_version: str = "2.0"
    #: Richer-track element/attr names (M3.1); a peer can rename them.
    track_element: str = "track"
    status_element: str = "status"
    attitude_element: str = "attitude"
    detection_element: str = "_meshsa_det"
    battery_attr: str = "battery"
    vendor_element: str = "_meshsa"
    #: Gates the additive richer-detail children entirely.
    emit_detail: bool = True

    def event(self, uid: str, etype: str, ts: float) -> ET.Element:
        """The ``<event>`` root with the house ``how``/``time``/``start``/``stale`` stamps."""
        return ET.Element(
            "event",
            version=self.cot_version,
            uid=uid,
            type=etype,
            how=self.how,
            time=_iso(ts),
            start=_iso(ts),
            stale=_iso(ts + self.stale_s),
        )

    def kind_for(self, etype: str) -> MessageKind:
        """Classify a non-chat event type, symmetric with encode.

        The configured ``marker_type`` classifies as MARKER even though it may start with
        ``a-``; then the configured PLI type (or the ``a-`` fallback) is PLI; anything else
        is a MARKER.
        """
        if etype == self.marker_type:
            return MessageKind.MARKER
        if etype == self.pli_type or etype.startswith("a-"):
            return MessageKind.PLI
        return MessageKind.MARKER


# -- encode ---------------------------------------------------------------------


def encode_envelope(naming: _CotNaming, envelope: Envelope) -> bytes:
    """Dispatch on the envelope kind: CHAT → GeoChat, MARKER → detection point, else PLI."""
    if envelope.kind == MessageKind.CHAT:
        return encode_chat(naming, envelope)
    if envelope.kind == MessageKind.MARKER:
        return encode_marker(naming, envelope)
    return encode_pli(naming, envelope)


def _point(ev: ET.Element, pos: dict[str, Any]) -> None:
    ET.SubElement(
        ev,
        "point",
        lat=str(pos.get("lat", 0.0)),
        lon=str(pos.get("lon", 0.0)),
        hae=str(pos.get("hae", 0.0)),
        ce=str(pos.get("ce", UNKNOWN_ERROR_M)),
        le=str(pos.get("le", UNKNOWN_ERROR_M)),
    )


def encode_pli(naming: _CotNaming, env: Envelope) -> bytes:
    """A position track of the (friendly) ``pli_type`` with contact/group detail."""
    node = env.payload.get("node", {})
    pos = env.payload.get("position", {})
    ev = naming.event(env.source_uid, naming.pli_type, env.ts)
    _point(ev, pos)
    detail = ET.SubElement(ev, "detail")
    ET.SubElement(detail, "contact", callsign=str(node.get("callsign", env.source_uid)))
    ET.SubElement(detail, "__group", name=str(node.get("tier", "")), role="Team Member")
    if naming.emit_detail:
        _emit_richer_detail(naming, detail, pos, env.payload.get("telemetry") or {})
    return ET.tostring(ev)


def _detection_attrs(det: dict[str, Any], label: str) -> dict[str, str] | None:
    """The vendor detection element's attributes, or ``None`` when there is no confidence.

    Only emitted when actual detection data exists (confidence is required by the model).
    """
    conf = det.get("confidence")
    if conf is None:
        return None
    attrs = {"label": label, "confidence": str(conf)}
    if det.get("track_id") is not None:
        attrs["track_id"] = str(det["track_id"])
    if det.get("bearing_deg") is not None:
        attrs["bearing_deg"] = str(det["bearing_deg"])
    return attrs


def _marker_remarks(det: dict[str, Any], label: str) -> str:
    conf = det.get("confidence")
    remarks = label if conf is None else f"{label} {float(conf) * 100:.0f}%"
    if det.get("bearing_deg") is not None:
        remarks += f" bearing {float(det['bearing_deg']):.0f}°"
    return remarks


def encode_marker(naming: _CotNaming, env: Envelope) -> bytes:
    """Encode an object-detection MARKER as a CoT point of the marker type.

    Distinct from :func:`encode_pli` (which stamps the friendly ``pli_type``): a detection
    gets ``marker_type`` so ATAK does not render it as a friendly track. The class label +
    confidence go into both ``<contact callsign>`` (so the marker is labelled on the map)
    and a ``<remarks>`` line, plus a vendor detection element for lossless round-trip.
    ``ce``/``le`` carry the (often crude) position error.
    """
    # ``or {}`` (not ``.get(k, {})``): a key explicitly set to None must still
    # fall back to a dict, not None.
    pos = env.payload.get("position") or {}
    det = env.payload.get("detection") or {}
    node = env.payload.get("node") or {}
    label = str(det.get("label", "detection"))
    # The map callsign honors a configured node.callsign (DetectionCodec sets it to the
    # class label by default, or an override), falling back to the class label.
    callsign = str(node.get("callsign", label))
    # CoT uid is the entity key in TAK/ATAK: a per-track uid (source:track) gives one
    # updated marker per tracked object instead of every detection overwriting the same
    # uid. Falls back to the detector uid when there is no tracker id.
    track_id = det.get("track_id")
    uid = f"{env.source_uid}:{track_id}" if track_id is not None else env.source_uid
    ev = naming.event(uid, naming.marker_type, env.ts)
    _point(ev, pos)
    detail = ET.SubElement(ev, "detail")
    ET.SubElement(detail, "contact", callsign=callsign)
    det_attrs = _detection_attrs(det, label)
    if det_attrs is not None:
        ET.SubElement(detail, naming.detection_element, det_attrs)
    ET.SubElement(detail, "remarks").text = _marker_remarks(det, label)
    return ET.tostring(ev)


def _emit_richer_detail(
    naming: _CotNaming, detail: ET.Element, pos: dict[str, Any], telemetry: dict[str, Any]
) -> None:
    """Append the additive (M3.1) track/status/vendor/attitude children.

    Every child is guarded: only emitted when its source data are present, so
    a plain PLI yields no richer detail and old readers ignore what they do
    not recognise.
    """
    course = pos.get("course_deg")
    speed = pos.get("speed_ms")
    if course is not None and speed is not None:
        ET.SubElement(detail, naming.track_element, course=str(course), speed=str(speed))

    battery_pct = telemetry.get("battery_pct")
    if battery_pct is not None:
        ET.SubElement(detail, naming.status_element, {naming.battery_attr: str(battery_pct)})

    vendor_attrs: dict[str, str] = {
        attr: str(telemetry[key])
        for attr, key in (("battery_v", "battery_v"), ("current_a", "current_a"))
        if telemetry.get(key) is not None
    }
    if vendor_attrs:
        ET.SubElement(detail, naming.vendor_element, vendor_attrs)

    attitude = telemetry.get("attitude") or {}
    att_attrs: dict[str, str] = {
        attr: str(attitude[key])
        for attr, key in (("roll", "roll_deg"), ("pitch", "pitch_deg"), ("yaw", "yaw_deg"))
        if attitude.get(key) is not None
    }
    if att_attrs:
        ET.SubElement(detail, naming.attitude_element, att_attrs)


def encode_chat(naming: _CotNaming, env: Envelope) -> bytes:
    """A GeoChat event: the text in ``<remarks>``, the room in ``<__chat>``."""
    text = env.payload.get("text", "")
    ev = naming.event(env.msg_id, naming.chat_type, env.ts)
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
    ET.SubElement(chat, "chatgrp", uid0=env.source_uid, uid1=str(env.payload.get("to") or "All"))
    ET.SubElement(detail, "remarks").text = text
    return ET.tostring(ev)


# -- decode ---------------------------------------------------------------------


def _parse_event(data: bytes) -> tuple[ET.Element, str, str, float]:
    """Parse the root ``<event>``; any failure is one :class:`MeshSAError` (undecodable)."""
    try:
        ev = ET.fromstring(data)
        if ev.tag != "event":
            raise ValueError("root is not <event>")
        uid = ev.attrib["uid"]
        etype = ev.attrib.get("type", "")
        ts = _parse_ts(ev.attrib.get("time", _iso(0)))
    except Exception as exc:
        raise MeshSAError(f"undecodable CoT ({len(data)} bytes): {exc}") from exc
    return ev, uid, etype, ts


def _envelope(
    ev: ET.Element, uid: str, ts: float, kind: MessageKind, payload: dict[str, Any]
) -> Envelope:
    # CoT carries no meshsa wire schema, so decode always stamps the current SCHEMA_VERSION.
    return Envelope(
        schema_version=SCHEMA_VERSION,
        msg_id=f"{uid}:{ev.attrib.get('time', '')}",
        ts=ts,
        source_uid=uid,
        kind=kind,
        payload=payload,
    )


def _decode_chat(ev: ET.Element, uid: str, ts: float, detail: ET.Element | None) -> Envelope:
    remarks = detail.find("remarks") if detail is not None else None
    text = (remarks.text or "") if remarks is not None else ""
    return _envelope(ev, uid, ts, MessageKind.CHAT, {"text": text, "to": None})


def _decode_point(pt: ET.Element | None) -> dict[str, Any]:
    pos: dict[str, Any] = {
        "lat": 0.0,
        "lon": 0.0,
        "hae": 0.0,
        "ce": UNKNOWN_ERROR_M,
        "le": UNKNOWN_ERROR_M,
    }
    if pt is not None:
        for key in pos:
            if key in pt.attrib:
                pos[key] = float(pt.attrib[key])
    return pos


def _validated_track(
    pos: dict[str, Any], telemetry: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate the assembled position/telemetry against the model contracts.

    An untrusted peer cannot inject out-of-range values (course/speed/battery) that bypass
    the pydantic validators — CoT decode builds dicts directly. Reuses the model validators
    (DRY) and surfaces violations as :class:`MeshSAError`, consistent with the telemetry
    codec's decode.
    """
    try:
        pos = Position.model_validate(pos).model_dump(exclude_none=True)
        if telemetry:
            telemetry = Telemetry.model_validate(telemetry).model_dump(exclude_none=True)
    except ValidationError as exc:
        raise MeshSAError(f"invalid CoT track values: {exc}") from exc
    return pos, telemetry


def decode_event(naming: _CotNaming, data: bytes) -> Envelope:
    """Decode one CoT event into an :class:`Envelope` (CHAT, PLI or MARKER)."""
    ev, uid, etype, ts = _parse_event(data)
    detail = ev.find("detail")
    if etype.startswith("b-t-f") or etype.startswith("b.t.f"):
        return _decode_chat(ev, uid, ts, detail)

    pos = _decode_point(ev.find("point"))
    contact = detail.find("contact") if detail is not None else None
    callsign = contact.attrib.get("callsign", uid) if contact is not None else uid
    telemetry: dict[str, Any] = {}
    if detail is not None:
        _decode_richer_detail(naming, detail, pos, telemetry)
    pos, telemetry = _validated_track(pos, telemetry)

    kind = naming.kind_for(etype)
    payload: dict[str, Any] = {"node": {"uid": uid, "callsign": callsign}, "position": pos}
    if telemetry:
        payload["telemetry"] = telemetry
    detection = _decode_detection(naming, detail) if kind == MessageKind.MARKER else None
    if detection is not None:
        payload["detection"] = detection
    return _envelope(ev, uid, ts, kind, payload)


def _decode_detection(naming: _CotNaming, detail: ET.Element | None) -> dict[str, Any] | None:
    """Parse the vendor detection element back into a validated detection dict.

    Returns None when absent. Numeric attrs come from untrusted peers, so the
    parse is validated via :class:`Detection` and surfaced as MeshSAError on bad
    values (consistent with the richer-detail decode)."""
    el = detail.find(naming.detection_element) if detail is not None else None
    # confidence is required by the Detection model — an element without it
    # is a legacy/empty marker, not an actual detection.
    if el is None or "confidence" not in el.attrib:
        return None
    raw: dict[str, Any] = {"label": el.attrib.get("label", "detection")}
    try:
        raw["confidence"] = float(el.attrib["confidence"])
        if "track_id" in el.attrib:
            raw["track_id"] = int(el.attrib["track_id"])
        if "bearing_deg" in el.attrib:
            raw["bearing_deg"] = float(el.attrib["bearing_deg"])
        return Detection.model_validate(raw).model_dump(exclude_none=True)
    except (TypeError, ValueError, ValidationError) as exc:
        raise MeshSAError(f"invalid detection detail in CoT: {exc}") from exc


def _decode_track(naming: _CotNaming, detail: ET.Element, pos: dict[str, Any]) -> None:
    track = detail.find(naming.track_element)
    if track is None:
        return
    if "course" in track.attrib:
        pos["course_deg"] = float(track.attrib["course"])
    if "speed" in track.attrib:
        pos["speed_ms"] = float(track.attrib["speed"])


def _decode_status_and_vendor(
    naming: _CotNaming, detail: ET.Element, telemetry: dict[str, Any]
) -> None:
    status = detail.find(naming.status_element)
    if status is not None and naming.battery_attr in status.attrib:
        # via float() so a peer sending a float string (e.g. "75.0")
        # is accepted, not rejected by int("75.0").
        telemetry["battery_pct"] = int(float(status.attrib[naming.battery_attr]))
    vendor = detail.find(naming.vendor_element)
    if vendor is not None:
        for key in ("battery_v", "current_a"):
            if key in vendor.attrib:
                telemetry[key] = float(vendor.attrib[key])


def _decode_attitude(naming: _CotNaming, detail: ET.Element, telemetry: dict[str, Any]) -> None:
    attitude = detail.find(naming.attitude_element)
    if attitude is None:
        return
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


def _decode_richer_detail(
    naming: _CotNaming, detail: ET.Element, pos: dict[str, Any], telemetry: dict[str, Any]
) -> None:
    """Parse the additive (M3.1) detail children back, lossless, ignoring any unknown
    children. Mutates ``pos`` and ``telemetry`` in place.

    Numeric attributes come from untrusted peers, so every ``float``/``int`` parse is
    guarded: a malformed value (e.g. ``course="invalid"``) is surfaced as a
    :class:`MeshSAError` rather than escaping as a raw ``ValueError``/``TypeError``.
    """
    try:
        _decode_track(naming, detail, pos)
        _decode_status_and_vendor(naming, detail, telemetry)
        _decode_attitude(naming, detail, telemetry)
    except (TypeError, ValueError) as exc:
        _log.debug(
            "malformed richer detail in CoT",
            detail=ET.tostring(detail, encoding="unicode"),
            error=str(exc),
        )
        raise MeshSAError(f"invalid richer detail in CoT: {exc}") from exc


# -- facade ---------------------------------------------------------------------


class CotCodec:
    """The registry-facing CoT codec: owns a :class:`_CotNaming`, dispatches to the functions.

    Schema-agnostic: CoT XML carries no meshsa wire schema, so there is no
    ``supported_schemas`` gate; decode always stamps the current ``SCHEMA_VERSION``.
    """

    name = "cot"

    def __init__(
        self,
        *,
        stale_s: float = DEFAULT_COT_STALE_S,
        how: str = "m-g",
        pli_type: str = "a-f-G-U-C",
        chat_type: str = "b-t-f",
        marker_type: str = "a-u-G",
        cot_version: str = "2.0",
        track_element: str = "track",
        status_element: str = "status",
        attitude_element: str = "attitude",
        detection_element: str = "_meshsa_det",
        battery_attr: str = "battery",
        vendor_element: str = "_meshsa",
        emit_detail: bool = True,
        **_: object,
    ) -> None:
        self.naming = _CotNaming(
            stale_s=stale_s,
            how=how,
            pli_type=pli_type,
            chat_type=chat_type,
            marker_type=marker_type,
            cot_version=cot_version,
            track_element=track_element,
            status_element=status_element,
            attitude_element=attitude_element,
            detection_element=detection_element,
            battery_attr=battery_attr,
            vendor_element=vendor_element,
            emit_detail=emit_detail,
        )

    @property
    def stale_s(self) -> float:
        """The configured stale window (read by node wiring and tests)."""
        return self.naming.stale_s

    def encode(self, envelope: Envelope) -> bytes:
        return encode_envelope(self.naming, envelope)

    def decode(self, data: bytes) -> Envelope:
        return decode_event(self.naming, data)


@codec_registry.register("cot")
def _make_cot(**kwargs: Any) -> CotCodec:
    return CotCodec(**kwargs)
