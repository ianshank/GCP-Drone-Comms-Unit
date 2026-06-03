"""Per-codec supported_schemas: lets codec versions coexist on one node."""

import pytest

from meshsa import CompactCodec, Envelope, IncompatibleSchemaError, JsonCodec, MessageKind
from meshsa.version import SUPPORTED_SCHEMAS


def _chat(schema=1):
    return Envelope(
        schema_version=schema,
        msg_id="m",
        ts=1.0,
        source_uid="u",
        kind=MessageKind.CHAT,
        payload={"text": "hi", "to": None},
    )


def test_default_supported_schemas_is_compat_window():
    assert JsonCodec().supported_schemas == SUPPORTED_SCHEMAS
    assert CompactCodec().supported_schemas == SUPPORTED_SCHEMAS


def test_json_codec_explicit_supported_schemas_rejects_out_of_set():
    codec = JsonCodec(supported_schemas=[2])  # accepts only schema 2
    frame = JsonCodec().encode(_chat(1))  # a schema-1 frame
    assert codec.supported_schemas == frozenset({2})
    with pytest.raises(IncompatibleSchemaError):
        codec.decode(frame)


def test_compact_codec_explicit_supported_schemas_rejects_out_of_set():
    codec = CompactCodec(supported_schemas=[2])
    frame = CompactCodec().encode(_chat(1))
    with pytest.raises(IncompatibleSchemaError):
        codec.decode(frame)
