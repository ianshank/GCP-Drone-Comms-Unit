---
name: meshsa-test-conventions
description: "Use when: writing meshsa tests, fixing flaky async tests, preserving pytest coverage, using FakeClock, SeqIdFactory, LoopbackBus, fake Meshtastic, fake TAK, or bridge e2e tests."
argument-hint: "Code path under test and whether async, codec, transport, or config behavior is involved"
---

# MeshSA Test Conventions

## When to Use

- Add tests for framework code, transports, codecs, config, or the router.
- Fix a flaky async test.
- Preserve coverage while adding new behavior.

## Procedure

1. Put tests under `packages/meshsa/tests/` with `test_*.py` names.
2. Use `pytest-asyncio` native async tests; the project config sets
   `asyncio_mode = "auto"`.
3. Use `FakeClock` and `SeqIdFactory` from `tests/conftest.py` for deterministic
   timestamps and message IDs.
4. Use `LoopbackBus` and `LoopbackTransport` for in-process bridge behavior.
5. For real transports, inject fake connectors, fake pubsub functions, fake I/O,
   and fake sleep functions. Do not open real serial devices or sockets in unit CI.
6. For targeted test runs, remember that project coverage may fail because only a
   subset ran. Run `python -m pytest` for the final coverage gate.
7. Keep assertions semantic: decoded `Envelope` fields, payload values, registry
   behavior, reconnect state, and delivery counts.
8. After tests pass, run mypy and ruff from `packages/meshsa`.

## References

- `packages/meshsa/tests/conftest.py`
- `packages/meshsa/tests/test_node.py`
- `packages/meshsa/tests/test_router.py`
- `packages/meshsa/tests/test_router_codecs.py`
- `packages/meshsa/tests/test_bridge_e2e.py`