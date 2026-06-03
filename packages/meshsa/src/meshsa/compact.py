"""Compact binary codec for LoRa-sized links (Meshtastic ~237 B payload).

A PLI that serialises to ~230+ bytes as JSON encodes to ~40 bytes here, so the
framework's own envelopes actually fit a single Meshtastic packet. Lossy by design
for a radio link: lat/lon are scaled int32 (~1.1 cm), altitude is integer metres,
and ce/le are clamped to uint16 (65535 = "unknown/large"). PLI and CHAT have tight
encodings; any other kind falls back to a length-prefixed compact-JSON payload so
the codec stays lossless for the fields it claims and total for the rest.

Wire layout (big-endian):
  u8 schema | u8 kind | u32 ts | str source_uid | str msg_id | <kind body>
    PLI/MARKER body : i32 lat_e7 | i32 lon_e7 | i32 hae_m | u16 ce | u16 le |
                      str callsign | u8 tier
    CHAT body       : str to | u16 len | text
    other body      : u16 len | compact-JSON(payload)
  str = u8 length + UTF-8 bytes (<=255).
"""

from __future__ import annotations

import json
import struct
from collections.abc import Iterable
from typing import Any

from .errors import IncompatibleSchemaError, MeshSAError
from .models import Envelope, MessageKind, NodeTier
from .registry import codec_registry
from .version import SUPPORTED_SCHEMAS

_KINDS = [k.value for k in MessageKind]  # index == wire kind byte
_TIERS = [t.value for t in NodeTier]
_LATLON_SCALE = 1e7
_U16_MAX = 0xFFFF
_POSITION_KINDS = (MessageKind.PLI, MessageKind.MARKER)


def _put_str(buf: bytearray, s: str) -> None:
    b = s.encode("utf-8")
    if len(b) > 255:
        raise MeshSAError("string too long for compact codec (max 255 bytes)")
    buf.append(len(b))
    buf += b


def _get_str(data: bytes, off: int) -> tuple[str, int]:
    n = data[off]
    off += 1
    return data[off : off + n].decode("utf-8"), off + n


def _clamp_u16(v: float) -> int:
    iv = int(round(v))
    if iv < 0:
        return 0
    return iv if iv < _U16_MAX else _U16_MAX


class CompactCodec:
    name = "compact"
    #: Wire schemas this codec instance accepts on decode.
    supported_schemas: frozenset[int] = SUPPORTED_SCHEMAS

    def __init__(self, *, supported_schemas: Iterable[int] | None = None, **_: Any) -> None:
        if supported_schemas is not None:
            self.supported_schemas = frozenset(supported_schemas)

    def encode(self, envelope: Envelope) -> bytes:
        kind_idx = _KINDS.index(envelope.kind.value)  # MessageKind guarantees membership
        out = bytearray()
        out.append(envelope.schema_version & 0xFF)
        out.append(kind_idx)
        out += struct.pack(">I", int(envelope.ts) & 0xFFFFFFFF)
        _put_str(out, envelope.source_uid)
        _put_str(out, envelope.msg_id)

        if envelope.kind in _POSITION_KINDS:
            node = envelope.payload.get("node", {})
            pos = envelope.payload.get("position", {})
            out += struct.pack(
                ">iii",
                int(round(pos.get("lat", 0.0) * _LATLON_SCALE)),
                int(round(pos.get("lon", 0.0) * _LATLON_SCALE)),
                int(round(pos.get("hae", 0.0))),
            )
            out += struct.pack(
                ">HH", _clamp_u16(pos.get("ce", _U16_MAX)), _clamp_u16(pos.get("le", _U16_MAX))
            )
            _put_str(out, str(node.get("callsign", envelope.source_uid)))
            tier = str(node.get("tier", _TIERS[0]))
            out.append(_TIERS.index(tier) if tier in _TIERS else 0)
        elif envelope.kind == MessageKind.CHAT:
            _put_str(out, envelope.payload.get("to") or "")
            text = (envelope.payload.get("text") or "").encode("utf-8")
            out += struct.pack(">H", len(text))
            out += text
        else:
            blob = json.dumps(envelope.payload, separators=(",", ":")).encode("utf-8")
            out += struct.pack(">H", len(blob))
            out += blob
        return bytes(out)

    def decode(self, data: bytes) -> Envelope:
        payload: dict[str, Any]
        try:
            schema = data[0]
            if schema not in self.supported_schemas:
                raise IncompatibleSchemaError(f"schema {schema} not supported")
            kind = MessageKind(_KINDS[data[1]])
            ts = struct.unpack_from(">I", data, 2)[0]
            off = 6
            source_uid, off = _get_str(data, off)
            msg_id, off = _get_str(data, off)

            if kind in _POSITION_KINDS:
                lat_e7, lon_e7, hae = struct.unpack_from(">iii", data, off)
                off += 12
                ce, le = struct.unpack_from(">HH", data, off)
                off += 4
                callsign, off = _get_str(data, off)
                tier_idx = data[off]
                payload = {
                    "node": {"uid": source_uid, "callsign": callsign, "tier": _TIERS[tier_idx]},
                    "position": {
                        "lat": lat_e7 / _LATLON_SCALE,
                        "lon": lon_e7 / _LATLON_SCALE,
                        "hae": float(hae),
                        "ce": float(ce),
                        "le": float(le),
                    },
                }
            elif kind == MessageKind.CHAT:
                to, off = _get_str(data, off)
                tlen = struct.unpack_from(">H", data, off)[0]
                off += 2
                text = data[off : off + tlen].decode("utf-8")
                payload = {"text": text, "to": to or None}
            else:
                blen = struct.unpack_from(">H", data, off)[0]
                off += 2
                payload = json.loads(data[off : off + blen].decode("utf-8"))
        except IncompatibleSchemaError:
            raise
        except Exception as exc:
            raise MeshSAError(f"undecodable compact frame: {exc}") from exc
        return Envelope(
            schema_version=schema,
            msg_id=msg_id,
            ts=float(ts),
            source_uid=source_uid,
            kind=kind,
            payload=payload,
        )


@codec_registry.register("compact")
def _make_compact(**_: object) -> CompactCodec:
    return CompactCodec()
