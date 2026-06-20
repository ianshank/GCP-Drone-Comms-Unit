---
name: meshsa-add-codec
description: "Use when: adding a meshsa codec, changing JSON/Compact/CoT encoding, wire format, codec registry, Envelope serialization, per-transport codec bridge, or decode compatibility."
argument-hint: "Codec name, wire format, schema compatibility, and roundtrip expectations"
---

# Add a MeshSA Codec

## When to Use

- Add a new wire encoding for `Envelope`.
- Change `JsonCodec`, `CompactCodec`, `CotCodec`, or per-transport encoding.
- Debug bridge translation between mesh and TAK sides.

## Procedure

1. Read [../../../packages/meshsa/AGENTS.md](../../../packages/meshsa/AGENTS.md).
2. Implement `encode(envelope: Envelope) -> bytes` and
   `decode(data: bytes) -> Envelope`.
3. Register the codec with `@codec_registry.register("name")`.
4. On decode, reject incompatible schemas with `IncompatibleSchemaError` or a
   codec-specific `MeshSAError` path that the router can drop safely.
5. Preserve `Envelope.kind`, `msg_id`, `source_uid`, timestamp, and payload fields
   unless the codec explicitly maps to a lossy external protocol such as CoT.
6. Add roundtrip tests, malformed-frame tests, and bridge tests when the codec is
   used per transport.
7. For LoRa/Meshtastic work, prefer `compact` over JSON and document size tradeoffs.
8. Run the package verification commands before marking done.

## References

- `packages/meshsa/src/meshsa/codec.py`
- `packages/meshsa/src/meshsa/compact.py`
- `packages/meshsa/src/meshsa/cot.py`
- `packages/meshsa/src/meshsa/router.py`
- `packages/meshsa/tests/test_registry_codec.py`
- `packages/meshsa/tests/test_router_codecs.py`