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
| `meshsa.errors`                 | Exception hierarchy rooted at `MeshSAError`; `CommandError` family inherits from it |
| `meshsa.protocols`              | `Transport`, `Codec`, `Clock`, `IdFactory` Protocols + defaults      |
| `meshsa.models`                 | `Position`, `NodeInfo`, `Envelope`, `PliPayload`, `ChatPayload`, `UNKNOWN_ERROR_M` |
| `meshsa.config`                 | `NodeConfig`, `MeshConfig`, `RouterConfig`, `HealthConfig`, `TransportConfig` |
| `meshsa.registry`               | Generic `Registry[T]`; `transport_registry`, `codec_registry`        |
| `meshsa.plugins`                | `load_plugins()` — opt-in entry-point discovery of out-of-tree drivers |
| `meshsa.codec`                  | `JsonCodec` (Envelope <-> bytes); per-codec `supported_schemas`      |
| `meshsa.compact`                | `CompactCodec` (LoRa-sized binary, ~40 B)                            |
| `meshsa.cot`                    | `CotCodec` (ATAK / TAK Cursor-on-Target XML; schema-agnostic)       |
| `meshsa.router`                 | Async broker: dedupe, bridge, per-transport codec selection; resilient subscriber dispatch; `RouterMetrics` |
| `meshsa.metrics`                | `RouterMetrics` counters (rx/tx/forwarded/dropped/schema-mismatch)  |
| `meshsa.health`                 | `health_snapshot()` + opt-in `/healthz` aiohttp listener (`[health]`) |
| `meshsa.node`                   | `Node` dataclass + `build_node(config)` factory (codec-instance injection) |
| `meshsa.cli`                    | `meshsa-base` console entry point (argparse/build_config/run)        |
| `meshsa.transports.base`        | `AbstractTransport` (async inbox, bounded drop-newest, `stream()`)  |
| `meshsa.transports.loopback`    | `LoopbackBus`, `LoopbackTransport`, `NullTransport`                  |
| `meshsa.transports.meshtastic_radio` | Real Meshtastic (USB / TCP / BLE), reconnect supervisor + mesh provisioning |
| `meshsa.transports.tak`         | `TakTcpTransport`, `TakMulticastTransport` for FreeTAKServer / ATAK  |
| `meshsa.inference`              | `NemotronClient` + `InferenceService`: opt-in NVIDIA NIM AI bridge (`[inference]` extra) |
| `meshsa.command`                | Supervised command path: staging, confirmation, audit, MAVLink link + pump |
| `meshsa.command.errors`         | `CommandError(MeshSAError)` + typed refusal sub-hierarchy             |
| `meshsa.cv.geo`                 | Pure pixel→lat/lon projection (`project_to_ground`, `Terrain` seam, covariance error) |
| `meshsa.scout`                  | Vineyard scouting: georef fusion, dedup, store, survey/mission export, `aiohttp` station (`[scout]` extra) |
| `meshsa.examples.base_node`     | Thin re-export of `meshsa.cli` (demonstrative only)                 |

## Patterns

### Dependency injection via `Protocol`
Anything I/O-shaped is a `typing.Protocol`. The router and node accept those types,
not concrete classes. This is what lets the test suite drive a 747-test, 99.7%
coverage run without hardware.

### Open/closed registries
`transport_registry` and `codec_registry` are generic `Registry[T]` instances.
Modules self-register at import time. Adding a new transport is "config + factory,
no core edits."

### Per-transport codec selection
The router's `_codec_for(transport)` map lets a single bridge run JSON over LoRa,
CoT over TAK TCP, and compact binary over Meshtastic simultaneously. Bridging
re-encodes when forwarding between transports of different codecs.

### Optional adjunct services
The node optionally attaches services that are out of the hot path:
- **`meshsa.health`**: `/healthz` + `/metrics` aiohttp listener (install with `[health]`).
- **`meshsa.llm`**: read-only situational-awareness assistant over telemetry + TAK tracks.
- **`meshsa.inference`**: NVIDIA Nemotron NIM AI bridge — subscribes to Router messages,
  sends traffic to the NIM API for tactical analysis, and broadcasts AI insight summaries
  (configurable prefix via `NemotronConfig.insight_prefix`). The HTTP boundary is an injectable
  `HttpTransport` `Protocol` (`HttpResponse` + the default socket-backed `AiohttpTransport`,
  which owns the reused `asyncio.Lock`-guarded session and maps native errors to the neutral
  model); the `NemotronClient` retry/backoff/parse logic is pure and fake-tested (no sockets,
  no `aiohttp`-version coupling). Backoff is exponential and **capped**
  (`backoff_base`/`backoff_max_s`); **non-429 4xx fail fast** while 429/5xx retry; failures
  surface as `InferenceTransportError`/`InferenceHttpError` (both `MeshSAError`), and a
  malformed completion body raises `InferenceError`, never a raw `KeyError`. Injectable `sleep`
  for testability. Lazy-imports `aiohttp`; install with `[inference]`. All config via
  `MESHSA_INFERENCE_*` environment variables (13 fields incl. `backoff_max_s`). Feedback-loop
  safe: messages matching the configured insight prefix are never re-analyzed.
  **Observability & backpressure:** `InferenceService.as_dict()` returns point-in-time
  counters (`offline_dropped`/`intake_dropped` monotonic counters,
  `offline_queue_depth`/`pending_tasks` gauges), surfaced on `/metrics` (both `prometheus` and
  `json` via `health.render_metrics`) as `meshsa_inference_offline_dropped_total`,
  `meshsa_inference_intake_dropped_total`, `meshsa_inference_offline_queue_depth`, and
  `meshsa_inference_pending_tasks`, only when `node.inference_service` is set.
  `NemotronConfig.max_pending_tasks` (`MESHSA_INFERENCE_MAX_PENDING_TASKS`, default `0` =
  unbounded) bounds `handle_message` task intake on a constrained edge node: once in-flight
  analysis tasks reach the cap, new messages are shed (drop-and-count into `_intake_dropped`),
  mirroring the existing offline-queue drop-and-count.

### Resilient subscriber dispatch
The router's `_pump` wraps each subscriber callback in `try/except`: a failing subscriber
is logged with `exc_info=True` and never crashes the pump or prevents other subscribers
from receiving messages. This ensures the message-delivery hot path is fault-tolerant.

### Env-var bindings
`NodeConfig.from_env()` reads `MESHSA_*` environment variables for all config sections:
scalar node fields, `MESHSA_MESH_*` (MeshConfig), `MESHSA_ROUTER_*` (RouterConfig),
`MESHSA_HEALTH_*` (HealthConfig), `MESHSA_INFERENCE_*` (NemotronConfig), and
`MESHSA_SCOUT_*` (ScoutConfig). Individual
env-vars always override the JSON blob value for the same field. Parsing uses shared
helpers (`parse_int`, `parse_float`, `_parse_bool`) that name the offending variable on
bad values. `MESHSA_INFERENCE_MAX_PENDING_TASKS` binds `NemotronConfig.max_pending_tasks`
(default `0` = unbounded) alongside the other `MESHSA_INFERENCE_*` fields. The
`jetson_yolo_gcs` package (see "Perception subsystem" below) is a separate process with its
own `pydantic-settings` config and is **not** read by `NodeConfig.from_env()`.

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

## Vineyard scouting subsystem (`meshsa.scout`)

`meshsa.scout` (`packages/meshsa/src/meshsa/scout/`) is a self-contained, offline,
hardware-free pipeline that turns a mapping survey into a georeferenced, deduplicated anomaly
map. It follows the same invariants as the rest of the framework and **reuses** the proven
primitives rather than forking them.

- **Reuse, not fork.** Georeferencing is the pure `meshsa.cv.geo` (extended additively with a
  `Terrain` seam, roll, and a covariance error model); pins reach ATAK through the existing
  `detection_codec → MARKER Envelope → cot` path (no codec edit, no schema bump); the station
  reuses `meshsa.netauth` (shared with `meshsa.llm.server`) for loopback/bearer/fail-closed bind.
- **`Protocol` seams, fakes-first (Invariant 3).** `PoseSource`/`DetectionSource`/`Terrain`/
  `Store` are injected; a seeded synthetic `replay` harness drives the whole pipeline with no
  radios/GPS/camera, and `--health-check` asserts known truths geolocate within the RTK budget
  and dedupe to the expected pin count.
- **Config-driven (Invariant 5).** Every tunable is a `ScoutConfig` field (`MESHSA_SCOUT_*`),
  composed into `NodeConfig`; camera intrinsics, DEM path, store path, and marker stale are all
  config, wired through `build_terrain` / `build_store` / `make_marker_codec` / `camera_from_config`.
- **Pose is the real work.** `mavlink_source` is position-only, so `PoseFuser` fuses `ATTITUDE`
  + position + terrain into a `cv.geo.Pose` with **true AGL**; `TimeSync` matches detections to
  the nearest pose (max-skew drop-and-count) and `Deduplicator` clusters at `vine_spacing/2`,
  anchored to each cluster's original position so a run of higher-confidence merges cannot chain
  the pin beyond the radius.
- **Offline mission export only (CHARTER §3 carve-out).** `survey` + `export_mission` emit QGC
  `.plan` / ArduPilot `.waypoints` (with an explicit WPL home row) as **inert files a human
  loads** — scout issues no vehicle commands and no MAVLink writes. The DEM raster read is the
  only `# pragma: no cover` glue (`[geo]`/rasterio extra); its grid-shaping and the bilinear
  math are pure and tested.

## Perception subsystem (`jetson_yolo_gcs`)

`jetson_yolo_gcs` (`packages/jetson_yolo_gcs/`) is a **self-contained** on-board camera
detection process: it converts YOLO detections into an opt-in MAVLink `LANDING_TARGET` for
advisory precision-landing guidance. It is a **separate package with its own config and test
suite** — it does not import `meshsa` and is not part of the gateway process. Hardware
validation of the `local_ned` path is still **pending**.

- **No-`meshsa` invariant.** The package must not import `meshsa`. Where a primitive is
  needed on both sides (georeferencing math, injectable pose/time seams), it is
  **reimplemented independently** rather than shared, so the two packages stay decoupled and
  deployable separately.
- **Pure, no-numpy projection (`geometry/ned.py`).** `project_pixel_to_ned(cam, cx, cy, *,
  alt_agl_m, heading_deg, pitch_deg, roll_deg=0.0) -> NedOffset | None` mirrors the flat-ground
  ray-cast in `meshsa.cv.geo.project_to_ground`, reimplemented independently to preserve the
  no-`meshsa`-import invariant. It is pure stdlib `math` (no numpy dependency, matching the
  framework-wide no-numpy invariant) and fails safe: it returns `None` for `alt_agl_m <= 0`, a
  degenerate `img_w`/`img_h <= 0`, or a projected ray at/above the horizon.
- **Injectable seams (`Protocol`s, fakes-first).** `mavlink/pose.py` defines
  `PoseSource` (`runtime_checkable` `Protocol`, `latest() -> VehiclePose | None`) with
  `MavlinkPoseSource` reducing ATTITUDE + an injected AGL reader into a pose; `mavlink/
  timesync.py` defines `TimeSync(offset_us=0)` + `to_vehicle_usec(local_s)` (the device-side
  TIMESYNC round-trip, `exchange()`, is hardware-only and `# pragma: no cover`). Both seams
  keep the bridge's angle/projection/time math unit-tested with fakes — no hardware, mirroring
  the framework's `Transport`/`Clock`/`IdFactory` DI pattern.
- **Frame-dispatched `LANDING_TARGET` (`mavlink/bridge.py`).** `MavlinkSettings.frame`
  (`Literal["body_frd", "local_ned"]`, default `body_frd`) selects the wire path. `body_frd`
  sends angular offsets about the vehicle body (byte-identical to the pre-existing wire
  format, pin-guarded). `local_ned` projects the detection through `geometry/ned.py` using the
  injected `PoseSource` and sends a `position_valid=1` North/East/Down position — but **only**
  when a pose is available and the ray is projectable.
- **Fail-safe suppression, reason-keyed.** A `local_ned` send is suppressed (no message sent)
  rather than emitting a bogus `position_valid=1` position when there is no `PoseSource`, no
  fresh pose, or an unprojectable ray. The fail-closed autopilot-**heartbeat** gate (a fresh
  HEARTBEAT must have been observed via `poll_heartbeat`) guards **both** the `body_frd` and
  `local_ned` send paths. Suppression reasons (`no_heartbeat` / `no_pose` / `unprojectable`)
  are counted distinctly via `_note_suppressed(reason, …)` and exposed by
  `suppressed_snapshot()`, surfaced through `Pipeline.snapshot()`'s
  `landing_target_suppressed_by_reason` (the aggregate `landing_target_suppressed` total is
  retained for backward compatibility).
- **Time source.** `LANDING_TARGET.time_usec` is the capture-time-aware
  `_compute_time_usec()`: `capture_time_source="publish"` (default) stamps the wall clock at
  send time (unchanged behavior); `capture_time_source="capture"` stamps the frame's own
  capture timestamp, and — only when `timesync_enabled=True` **and** a `TimeSync` is wired —
  applies the vehicle-clock offset on top. Both flags are load-bearing (each actually changes
  the stamp when flipped) rather than silent no-ops.
- **Config (`MAVLINK_*` env prefix, `pydantic-settings`).** `frame`, `timesync_enabled`
  (default `False`), and `capture_time_source` (default `"publish"`) join the existing
  `enable_landing_target` (default `False`, the CHARTER §3 opt-in carve-out) and
  `require_heartbeat` (default `True`, fail-closed) fields on `MavlinkSettings`. Named
  protocol constants replace magic literals: `_MAV_FRAME_LOCAL_NED = 1`,
  `_LANDING_TARGET_TYPE_LIGHT_BEACON = 0`, `_IDENTITY_QUATERNION_WXYZ` (identity quaternion,
  a tuple so it can't be mutated in place).
- **Hardware-free in tests.** As with `msp_source`/`mavlink_source` in `meshsa`, the pymavlink
  connection is always injected (`connection` / `connection_factory`), so every line of
  angle/projection/gating logic — including `recv_match` reads — is exercised by a fake; only
  the real connection factory (`_default_connection_factory`) is `# pragma: no cover`.
