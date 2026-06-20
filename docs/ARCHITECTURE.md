# Architecture

This document describes the structure and design of the `meshsa` framework that
ships as `packages/meshsa`. For project layout, see [CONTRIBUTING.md](../CONTRIBUTING.md).

## Goals

1. **Transport-agnostic.** Add new radios, IP transports, or TAK servers without
   touching core code.
2. **Wire-compatible.** Every framed message carries a `schema_version`; nodes
   running different builds can interoperate within the supported window.
3. **Testable without hardware.** All I/O sits behind structural-typed
   `Protocol`s; the test suite uses fakes for clocks, IDs, transports, and
   the Meshtastic / TAK glue.
4. **Zero hard-coded operational defaults.** Ports, intervals, callsigns, cache
   sizes, backoff curves are all Pydantic config fields.

## Module map

| Module                          | Purpose                                                              |
|---------------------------------|----------------------------------------------------------------------|
| `meshsa.version`                | `SCHEMA_VERSION`, `MIN_COMPATIBLE_SCHEMA`, `is_compatible()`, `SUPPORTED_SCHEMAS`, `warn_deprecated()` |
| `meshsa.errors`                 | Exception hierarchy rooted at `MeshSAError`                          |
| `meshsa.protocols`              | `Transport`, `Codec`, `Clock`, `IdFactory` Protocols + defaults      |
| `meshsa.models`                 | `Position`, `NodeInfo`, `Envelope`, `PliPayload`, `ChatPayload`, `UNKNOWN_ERROR_M` |
| `meshsa.config`                 | `NodeConfig`, `MeshConfig`, `RouterConfig`, `HealthConfig`, `TransportConfig` |
| `meshsa.registry`               | Generic `Registry[T]`; `transport_registry`, `codec_registry`        |
| `meshsa.plugins`                | `load_plugins()` — opt-in entry-point discovery of out-of-tree drivers |
| `meshsa.codec`                  | `JsonCodec` (Envelope <-> bytes); per-codec `supported_schemas`      |
| `meshsa.compact`                | `CompactCodec` (LoRa-sized binary, ~40 B)                            |
| `meshsa.cot`                    | `CotCodec` (ATAK / TAK Cursor-on-Target XML; schema-agnostic)       |
| `meshsa.router`                 | Async broker: dedupe, bridge, per-transport codec selection; `RouterMetrics` |
| `meshsa.metrics`                | `RouterMetrics` counters (rx/tx/forwarded/dropped/schema-mismatch)  |
| `meshsa.health`                 | `health_snapshot()` + opt-in `/healthz` aiohttp listener (`[health]`) |
| `meshsa.node`                   | `Node` dataclass + `build_node(config)` factory (codec-instance injection) |
| `meshsa.cli`                    | `meshsa-base` console entry point (argparse/build_config/run)        |
| `meshsa.transports.base`        | `AbstractTransport` (async inbox, bounded drop-newest, `stream()`)  |
| `meshsa.transports.loopback`    | `LoopbackBus`, `LoopbackTransport`, `NullTransport`                  |
| `meshsa.transports.meshtastic_radio` | Real Meshtastic (USB / TCP / BLE), reconnect supervisor + mesh provisioning |
| `meshsa.transports.tak`         | `TakTcpTransport`, `TakMulticastTransport` for FreeTAKServer / ATAK  |
| `meshsa.examples.base_node`     | Thin re-export of `meshsa.cli` (demonstrative only)                 |

## Patterns

### Dependency injection via `Protocol`
Anything I/O-shaped is a `typing.Protocol`. The router and node accept those types,
not concrete classes. This is what lets the test suite drive a 98-test, 100%
coverage run without hardware.

### Open/closed registries
`transport_registry` and `codec_registry` are generic `Registry[T]` instances.
Modules self-register at import time. Adding a new transport is "config + factory,
no core edits."

### Per-transport codec selection
The router's `_codec_for(transport)` map lets a single bridge run JSON over LoRa,
CoT over TAK TCP, and compact binary over Meshtastic simultaneously. Bridging
re-encodes when forwarding between transports of different codecs.

### Schema versioning
Every `Envelope` carries `schema_version: int`. Codecs compare against
`SCHEMA_VERSION` / `MIN_COMPATIBLE_SCHEMA` and raise `IncompatibleSchemaError`,
which the router catches and logs (the frame is dropped, not crashed).

### Forward-compatible config loading
`build_node()` skips unknown transport `type` entries instead of raising. This lets
older builds load configs that contain transports they do not yet understand.

## Compatibility policy

| Change                                  | Action                                      |
|-----------------------------------------|---------------------------------------------|
| Add an optional Envelope field          | None (Pydantic defaults handle it)          |
| Add a new payload kind                  | None (unknown kinds drop, no schema bump)   |
| Add a new transport / codec             | None (registry self-registration)           |
| Change Envelope shape (rename / remove) | Bump `SCHEMA_VERSION`, document in CHANGELOG|
| Drop support for an older build         | Raise `MIN_COMPATIBLE_SCHEMA`, document     |

See [docs/AUDIT_REPORT.md](AUDIT_REPORT.md) for known gaps and the prioritized
backlog.

## FPV ground-side telemetry subsystem

`meshsa.fpv` (`packages/meshsa/src/meshsa/fpv/`) is a self-contained subsystem that
ingests **CRSF** telemetry from an ELRS handset module over a single-wire half-duplex
UART, evaluates link health, logs synchronized sessions, and enforces a pre-flight arm
gate. It implements [Phase 0 Errata E1](specs/PHASE0_ERRATA.md) and
[Phase 1 Spec v1.1](specs/PHASE1_SPEC_v1_1.md).

```
CrsfLink.poll_inbound()  -- echo-suppressed frames (Errata E1.2)
        |
TelemetryParser.parse()  -- pure, big-endian, typed | None
        |
TelemetryStore.update()  -- latest + bounded history ring
        |                         |
LinkHealthMonitor          FlightLogger (single writer thread)
        |                         |
ConsoleAlertSink           manifest.json + rc/telemetry/events/frames .jsonl
        |
ArmGuard wraps RCLink     -- pre-flight arm interlock only (CHARTER §3 carve-out)
```

Design choices that keep it consistent with the framework invariants:

- **Reuses the framework seams, invents none.** Injected `Clock` (`MonotonicClock`),
  `@runtime_checkable` Protocols (`RCLink`/`AlertSink`/`CrsfSerial`), pydantic `FpvSettings`
  with explicit defaults (no magic numbers), `structlog.get_logger("meshsa.fpv.<x>")`, and
  the `transports/msp_source.py` injection + `# pragma: no cover` hardware-factory pattern.
- **Threading.** Only `FlightLogger` owns a thread (the writer). `CrsfLink` is poll-driven
  (the consumer calls `poll_inbound`); the `CrsfSerial.read` seam is non-blocking.
- **Dataset versioning is its own namespace.** `fpv/version.py` `DATASET_SCHEMA` and
  `fpv/dataset.py` govern the on-disk session contract independently of the meshtastic wire
  `SCHEMA_VERSION` — a logger format change never touches the wire window. Per-file JSONL
  header records make field *additions* non-breaking; rename/remove/retype bumps
  `DATASET_SCHEMA`.
- **Air-track seam (registered in 0.3.0):** `@transport_registry.register("crsf_source")`
  (`transports/crsf_source.py`) wraps `CrsfLink`, decodes the CRSF **GPS (0x02)** frame to a
  `GpsSensor`, and emits a position frame through the existing `telemetry` codec — so an FPV
  aircraft becomes an ATAK **air** track with no router/codec edits, per the open/closed
  invariant (same injection + `# pragma: no cover` hardware pattern as `msp_source`). Adding
  the `GpsSensor` telemetry type made it a new persisted dataset record, so `DATASET_SCHEMA`
  bumped **1 → 2** (v1 datasets still read; older builds correctly reject a v2 dataset).
- **Camera capture (Phase 2, shipped):** a `CaptureWriter` daemon thread (`fpv/camera.py`)
  reads frames from an injected `CameraSource` and writes real records to the
  `frames.jsonl` stream with the manifest `video` entry populated — additive, so
  `DATASET_SCHEMA` stays **2**. The capture backend is the only `# pragma: no cover` glue
  (swapped for v4l2/GStreamer on the production Jetson).
- **Command authority** is limited to a pre-flight arm interlock (`ArmGuard`) under the
  CHARTER §3 carve-out; the monitor never intervenes in flight.
