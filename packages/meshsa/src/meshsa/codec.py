"""Default JSON codec. A CoT/XML codec can be added later via ``codec_registry``
without touching the router."""

from __future__ import annotations

from .errors import IncompatibleSchemaError, MeshSAError
from .models import Envelope
from .registry import codec_registry
from .version import is_compatible


class JsonCodec:
    name = "json"

    def encode(self, envelope: Envelope) -> bytes:
        return envelope.model_dump_json().encode("utf-8")

    def decode(self, data: bytes) -> Envelope:
        try:
            envelope = Envelope.model_validate_json(data)
        except Exception as exc:  # malformed wire data
            raise MeshSAError(f"undecodable envelope: {exc}") from exc
        if not is_compatible(envelope.schema_version):
            raise IncompatibleSchemaError(f"schema {envelope.schema_version} not supported")
        return envelope


@codec_registry.register("json")
def _make_json_codec(**_: object) -> JsonCodec:
    return JsonCodec()
