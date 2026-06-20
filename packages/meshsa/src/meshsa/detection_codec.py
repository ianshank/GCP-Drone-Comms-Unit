"""Detection codec — turns an object-detection frame into a MARKER :class:`Envelope`.

The DeepStream/YOLO process (a *separate* process, see the deepstream-yolo11-cot plan)
emits one small self-describing JSON frame per tracked detection over a local socket;
the ``detection_ingest`` source transport hands each frame to this stateless codec,
which maps it to a ``MessageKind.MARKER`` Envelope. Paired with the ``cot`` codec on a
TAK leg, that becomes a CoT detection marker on the map (NOT a friendly PLI track —
``CotCodec`` stamps its ``marker_type`` for MARKER envelopes).

This mirrors :mod:`meshsa.telemetry` (which maps telemetry frames to PLI envelopes); the
only differences are ``kind=MARKER`` and the carried ``detection`` block (label, confidence,
tracker id, optional sensor-relative bearing). The frame already carries lat/lon — geodetic
projection (when a GPS/attitude platform exists) is done upstream by the detector process
via :mod:`meshsa.cv.geo`; without a fix the detector sends a sensor-relative ``bearing_deg``.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from .errors import MeshSAError
from .models import UNKNOWN_ERROR_M, Detection, Envelope, MessageKind, Position
from .registry import codec_registry
from .version import SCHEMA_VERSION

#: Frame keys that must be present to build a valid MARKER Envelope.
_REQUIRED = ("src", "msg_id", "ts", "lat", "lon", "label", "confidence")


class DetectionCodec:
    name = "detection"
    # Schema-agnostic like the telemetry/CoT codecs; decode stamps SCHEMA_VERSION.

    def __init__(self, **_: object) -> None:
        pass

    def encode(self, envelope: Envelope) -> bytes:
        """Serialise a MARKER envelope back to a detection frame (symmetry/round-trip).

        Validates the position/detection blocks (like ``TelemetryCodec.encode``) so the
        codec never emits an out-of-contract frame (e.g. a bogus 0,0 position from a
        missing block); invalid input surfaces as the codec's standard ``MeshSAError``.
        """
        node = envelope.payload.get("node", {})
        try:
            position = Position.model_validate(envelope.payload.get("position", {}))
            detection = Detection.model_validate(envelope.payload.get("detection", {}))
        except ValidationError as exc:
            raise MeshSAError(f"invalid detection envelope: {exc}") from exc
        frame: dict[str, Any] = {
            "src": envelope.source_uid,
            "callsign": node.get("callsign", detection.label),
            "msg_id": envelope.msg_id,
            "ts": envelope.ts,
            "lat": position.lat,
            "lon": position.lon,
            "hae": position.hae,
            "ce": position.ce,
            "le": position.le,
            "label": detection.label,
            "confidence": detection.confidence,
        }
        for key, val in (("track_id", detection.track_id), ("bearing_deg", detection.bearing_deg)):
            if val is not None:
                frame[key] = val
        return json.dumps(frame).encode("utf-8")

    def decode(self, data: bytes) -> Envelope:
        try:
            frame = json.loads(data)
        except Exception as exc:  # malformed JSON
            raise MeshSAError(f"undecodable detection frame: {exc}") from exc
        if not isinstance(frame, dict):
            raise MeshSAError("detection frame is not an object")
        missing = [k for k in _REQUIRED if k not in frame]
        if missing:
            raise MeshSAError(f"detection frame missing keys: {missing}")
        try:
            src = str(frame["src"])
            msg_id = str(frame["msg_id"])
            ts = float(frame["ts"])
            position = Position(
                lat=float(frame["lat"]),
                lon=float(frame["lon"]),
                hae=float(frame.get("hae", 0.0)),
                ce=float(frame.get("ce", UNKNOWN_ERROR_M)),
                le=float(frame.get("le", UNKNOWN_ERROR_M)),
            )
            detection = Detection(
                label=str(frame["label"]),
                confidence=float(frame["confidence"]),
                track_id=frame.get("track_id"),
                bearing_deg=frame.get("bearing_deg"),
            )
        except (TypeError, ValueError, ValidationError) as exc:
            raise MeshSAError(f"invalid detection frame: {exc}") from exc
        # Default the marker callsign to the class label so the map marker is labelled.
        callsign = str(frame.get("callsign", detection.label))
        payload: dict[str, Any] = {
            "node": {"uid": src, "callsign": callsign},
            "position": position.model_dump(exclude_none=True),
            "detection": detection.model_dump(exclude_none=True),
        }
        return Envelope(
            schema_version=SCHEMA_VERSION,
            msg_id=msg_id,
            ts=ts,
            source_uid=src,
            kind=MessageKind.MARKER,
            payload=payload,
        )


@codec_registry.register("detection")
def _make_detection(**kwargs: Any) -> DetectionCodec:
    return DetectionCodec(**kwargs)
