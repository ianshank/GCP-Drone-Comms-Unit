---
name: meshsa-schema-version-bump
description: "Use when: changing meshsa Envelope fields, schema_version, MIN_COMPATIBLE_SCHEMA, backward compatibility, wire compatibility, migrations, deprecations, or serialized payload shape."
argument-hint: "Schema change, compatibility impact, migration path, and affected codecs"
---

# Bump MeshSA Schema Version

## When to Use

- Add, rename, remove, or reinterpret fields on `Envelope` or wire payloads.
- Change compatibility rules in `meshsa.version`.
- Introduce a migration or deprecation path for old nodes.

## Procedure

1. Classify the change:
   - Optional additive field with default: usually no schema bump.
   - Rename, removal, or semantic change: bump `SCHEMA_VERSION`.
   - Dropping old nodes: raise `MIN_COMPATIBLE_SCHEMA` and document why.
2. Update `packages/meshsa/src/meshsa/version.py`.
3. Update every codec decode path that checks compatibility.
4. Add tests for old, current, and incompatible versions.
5. Add or update serialized snapshot/roundtrip tests when the wire shape changes.
6. Document the migration path in `CHANGELOG.md`, `docs/ARCHITECTURE.md`, and any
   user-facing config examples.
7. Run the full package suite and mypy before removing compatibility warnings.

## References

- `packages/meshsa/src/meshsa/version.py`
- `packages/meshsa/src/meshsa/models.py`
- `packages/meshsa/src/meshsa/codec.py`
- `packages/meshsa/src/meshsa/compact.py`
- `packages/meshsa/src/meshsa/cot.py`
- `packages/meshsa/tests/test_version_models.py`