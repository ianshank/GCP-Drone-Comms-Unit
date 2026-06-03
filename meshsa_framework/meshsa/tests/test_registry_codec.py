import pytest

from meshsa import (DuplicateRegistrationError, Envelope, IncompatibleSchemaError,
                    JsonCodec, MeshSAError, MessageKind, Registry,
                    UnknownComponentError, transport_registry)
from meshsa.version import SCHEMA_VERSION


def test_registry_register_create_has_available():
    reg: Registry = Registry("widget")

    @reg.register("w1")
    def _make(**kw):
        return ("w1", kw)

    assert reg.has("w1")
    assert "w1" in reg.available()
    assert reg.create("w1", x=1) == ("w1", {"x": 1})


def test_registry_duplicate_and_unknown():
    reg: Registry = Registry("widget")
    reg.register("a")(lambda **k: 1)
    with pytest.raises(DuplicateRegistrationError):
        reg.register("a")(lambda **k: 2)
    with pytest.raises(UnknownComponentError):
        reg.create("missing")


def test_builtin_transports_registered():
    assert transport_registry.has("loopback")
    assert transport_registry.has("null")


def test_codec_roundtrip():
    codec = JsonCodec()
    env = Envelope(msg_id="m1", ts=1.0, source_uid="u", kind=MessageKind.CHAT,
                   payload={"text": "hi"})
    assert codec.decode(codec.encode(env)) == env


def test_codec_rejects_incompatible_schema():
    codec = JsonCodec()
    bad = Envelope(schema_version=SCHEMA_VERSION + 5, msg_id="m", ts=1.0,
                   source_uid="u", kind=MessageKind.PLI)
    with pytest.raises(IncompatibleSchemaError):
        codec.decode(codec.encode(bad))


def test_codec_rejects_garbage():
    with pytest.raises(MeshSAError):
        JsonCodec().decode(b"not json")


def test_codec_via_registry():
    from meshsa import codec_registry
    codec = codec_registry.create("json")
    assert codec.name == "json"


def test_transport_factories_create():
    lo = transport_registry.create("loopback", name="lo")
    nu = transport_registry.create("null", name="nu")
    assert lo.name == "lo" and nu.name == "nu"
