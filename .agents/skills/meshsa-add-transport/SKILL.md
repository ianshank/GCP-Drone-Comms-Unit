---
name: meshsa-add-transport
description: "Use when: adding a meshsa transport, radio driver, Meshtastic path, TAK transport, HaLow/IP link, reconnect logic, transport registry entry, or Transport Protocol implementation."
argument-hint: "Transport name, medium, config fields, and expected send/receive behavior"
---

# Add a MeshSA Transport

## When to Use

- Add a new radio, serial, TCP, UDP, HaLow, LoRa, TAK, or IP transport.
- Change send/receive behavior, reconnect supervision, or transport config.
- Register a new `TransportConfig.type` value.

## Procedure

1. Read [../../../AGENTS.md](../../../AGENTS.md) and
   [../../../packages/meshsa/AGENTS.md](../../../packages/meshsa/AGENTS.md).
2. Add implementation under `packages/meshsa/src/meshsa/transports/`.
3. Prefer subclassing `AbstractTransport` when an async inbox and `stream()` are
   enough; otherwise implement the `Transport` Protocol exactly.
4. Register the factory with `@transport_registry.register("name")` and accept
   `name`, `queue_maxsize`, and `**options` where appropriate.
5. Keep operational values configurable through `TransportConfig.options` and
   Pydantic config. Do not hide ports, intervals, or backoff values in the router.
6. Write tests with injected fakes: fake connectors, fake pubsub, `LoopbackBus`,
   `FakeClock`, and `SeqIdFactory`. Do not require real hardware in unit tests.
7. Update `packages/meshsa/README.md` and `docs/ARCHITECTURE.md` if the new
   transport changes user-facing setup or the module map.
8. Verify with `python -m pytest`, `mypy src`, `ruff check .`, and
   `ruff format --check .` from `packages/meshsa`.

## References

- `packages/meshsa/src/meshsa/protocols.py`
- `packages/meshsa/src/meshsa/transports/base.py`
- `packages/meshsa/src/meshsa/transports/loopback.py`
- `packages/meshsa/src/meshsa/transports/tak.py`
- `packages/meshsa/src/meshsa/transports/meshtastic_radio.py`
- `packages/meshsa/tests/test_transports.py`
- `packages/meshsa/tests/test_meshtastic.py`
- `packages/meshsa/tests/test_tak.py`