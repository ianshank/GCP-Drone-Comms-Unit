"""Default JSON codec. A CoT/XML codec can be added later via ``codec_registry``
without touching the router."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .errors import IncompatibleSchemaError, MeshSAError
from .models import Envelope
from .registry import codec_registry
from .version import SUPPORTED_SCHEMAS


class JsonCodec:
    name = "json"
    #: Wire schemas this codec instance accepts on decode.
    supported_schemas: frozenset[int] = SUPPORTED_SCHEMAS

    def __init__(self, *, supported_schemas: Iterable[int] | None = None, **_: Any) -> None:
        if supported_schemas is not None:
            self.supported_schemas = frozenset(supported_schemas)

    def encode(self, envelope: Envelope) -> bytes:
        return envelope.model_dump_json().encode("utf-8")

    def decode(self, data: bytes) -> Envelope:
        try:
            envelope = Envelope.model_validate_json(data)
        except Exception as exc:  # malformed wire data
            raise MeshSAError(f"undecodable envelope: {exc}") from exc
        if envelope.schema_version not in self.supported_schemas:
            raise IncompatibleSchemaError(f"schema {envelope.schema_version} not supported")
        return envelope


@codec_registry.register("json")
def _make_json_codec(**kwargs: Any) -> JsonCodec:
    return JsonCodec(**kwargs)
