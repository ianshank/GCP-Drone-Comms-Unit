"""Telemetry codec — turns a structured telemetry frame into an :class:`Envelope`.

Source transports (MAVLink autopilots, Betaflight MSP) parse their wire protocols
in their own reader threads and emit a small, self-describing JSON frame; this
codec is the **stateless** map from that frame to a PLI ``Envelope`` (and back).
Keeping the stateful, stream-oriented parse inside the transport — and the codec a
pure per-frame function — is what lets the router call ``decode()`` once per frame.

A telemetry source becomes a track on every bridged transport: paired with the
``cot`` codec on a TAK leg (with an air ``pli_type``), a drone/FC position is
delivered to ATAK as an air track, with no core changes. Nothing is hard-coded —
the frame carries its own uid/callsign/position, and the air-vs-ground decision is
the *target* CoT codec's ``pli_type`` option, not this codec's concern.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from .errors import MeshSAError
from .models import Envelope, MessageKind, Position, Telemetry
from .registry import codec_registry
from .version import SCHEMA_VERSION

#: Frame keys that must be present to build a valid Envelope.
_REQUIRED = ("src", "msg_id", "ts", "lat", "lon")


class TelemetryCodec:
    name = "telemetry"
    # Schema-agnostic like the CoT codec: telemetry frames carry no meshsa wire
    # schema, so there is no supported_schemas gate; decode stamps SCHEMA_VERSION.

    def __init__(self, **_: object) -> None:
        # No tunables today; constructor kept for registry symmetry / future opts.
        pass

    def encode(self, envelope: Envelope) -> bytes:
        """Serialise a PLI envelope back to a telemetry frame (symmetry/round-trip).

        Telemetry sources are receive-only, so this is rarely exercised on the
        wire; it exists so ``telemetry`` is a complete, lossless ``Codec``.
        """
        node = envelope.payload.get("node", {})
        pos = envelope.payload.get("position", {})
        frame: dict[str, Any] = {
            "src": envelope.source_uid,
            "callsign": node.get("callsign", envelope.source_uid),
            "msg_id": envelope.msg_id,
            "ts": envelope.ts,
            "lat": pos.get("lat", 0.0),
            "lon": pos.get("lon", 0.0),
            "hae": pos.get("hae", 0.0),
        }
        # Carry optional richer-track fields only when present (exclude_none on
        # the wire so absent keys never leak; old readers ignore unknown keys).
        for key in ("course_deg", "speed_ms"):
            if pos.get(key) is not None:
                frame[key] = pos[key]
        telemetry = envelope.payload.get("telemetry")
        if telemetry is not None:
            block = Telemetry.model_validate(telemetry).model_dump(exclude_none=True)
            if block:
                frame["telemetry"] = block
        return json.dumps(frame).encode("utf-8")

    def decode(self, data: bytes) -> Envelope:
        try:
            frame = json.loads(data)
        except Exception as exc:  # malformed JSON
            raise MeshSAError(f"undecodable telemetry frame: {exc}") from exc
        if not isinstance(frame, dict):
            raise MeshSAError("telemetry frame is not an object")
        missing = [k for k in _REQUIRED if k not in frame]
        if missing:
            raise MeshSAError(f"telemetry frame missing keys: {missing}")
        try:
            src = str(frame["src"])
            msg_id = str(frame["msg_id"])
            ts = float(frame["ts"])
            position = Position(
                lat=float(frame["lat"]),
                lon=float(frame["lon"]),
                hae=float(frame.get("hae", 0.0)),
                course_deg=frame.get("course_deg"),
                speed_ms=frame.get("speed_ms"),
            )
            telemetry = frame.get("telemetry")
            telemetry_model = Telemetry.model_validate(telemetry) if telemetry is not None else None
        except (TypeError, ValueError, ValidationError) as exc:
            # bad types / out-of-range lat/lon (TypeError/ValueError) or a
            # pydantic field-validator rejection on Position/Telemetry
            # (ValidationError) — all surfaced as the codec's standard error.
            raise MeshSAError(f"invalid telemetry frame: {exc}") from exc
        callsign = str(frame.get("callsign", src))
        payload: dict[str, Any] = {
            "node": {"uid": src, "callsign": callsign},
            # exclude_none so absent richer keys never enter the payload/wire.
            "position": position.model_dump(exclude_none=True),
        }
        if telemetry_model is not None:
            block = telemetry_model.model_dump(exclude_none=True)
            if block:
                payload["telemetry"] = block
        return Envelope(
            schema_version=SCHEMA_VERSION,
            msg_id=msg_id,
            ts=ts,
            source_uid=src,
            kind=MessageKind.PLI,
            payload=payload,
        )


@codec_registry.register("telemetry")
def _make_telemetry(**kwargs: Any) -> TelemetryCodec:
    return TelemetryCodec(**kwargs)
