# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.5.0] - 2026-06-07

Pilot the FC from the host: a joystick → MSP RC control path with combined live telemetry.
Additive — no `Envelope`/schema change; existing transports/codecs are reused, not modified
(only a pure-function extraction in `msp_source`).

### Added
- **`meshsa.rc`** — tested, hardware-free control logic: Linux joystick event parsing
  (`parse_js_event`, `JoystickState`), stick/switch → RC channel mapping (`AxisChannel`,
  `ButtonChannel`, `ButtonGroupChannel` for N-position switches, `RcMapping`, `axis_to_us`),
  a pluggable `ChannelSource` (with `JoystickChannelSource`) for HITL/autonomy reuse, and the
  fixed-rate `MspPilot` loop (`RcSink`/`JoystickReader` seams). Safety: starts disarmed /
  throttle-min, never auto-arms, fails safe on stale input, disarms on stop.
- **`flightctl/rc_bridge.py`** + **`flightctl/configs/jetson_rc.json`** — the daemon that owns
  the FC serial, streams `MSP_SET_RAW_RC` from `/dev/input/js0`, and decimates the same handle
  to poll telemetry → CoT to FreeTAKServer. `--dry-run` (calibrate, no FC writes) and
  `--monitor` (MSP_RC read-back) for safe bring-up.
- **`FC_MODE=pilot`** in `start_all.sh` — runs FTS + FTS-UI + WebMap + rc_bridge, skipping the
  gateway and the whole MAVLink chain (rc_bridge owns the exclusive FC serial).

### Changed
- `transports/msp_source.py`: extracted the pure `build_telemetry_frame(..., seq=…)` helper and
  per-message readers (`DEFAULT_MSP_READERS`) reused by the RC bridge; `_to_frame`/`_default_poll`
  delegate to them. No behaviour change.
- Combined pilot telemetry uses `RoundRobinTelemetry` (one MSP read per call) so the poll never
  blocks the RC loop for three round-trips at once; `make_cot_publisher`/`load_mapping` keep the
  daemon's telemetry logic in the tested package.

### Hardened (pre-release audit)
- **Arm safety:** after any failsafe, the arm switch must be physically re-cycled before motors
  can spin again (no silent re-arm when stale input resumes with the switch still held).
- `RcMapping` validates `arm.channel`/`throttle_channel` at construction; `MspPilot` rejects
  `hz <= 0`; the daemon closes the FC serial and logs CoT-send failures on shutdown; `start_all`
  no longer pins a `0,0` "Null Island" track and gives `rc-bridge` extra shutdown grace so the
  final disarm completes.

### Tests
- New integration/e2e/regression suites (no hardware — injected board/poll/readers/connectors):
  `test_msp_bridge_e2e.py` (MSP fix/fallback/remarks → CoT air track through `build_node`),
  `test_flightctl_configs.py` (the shipped `jetson_gateway.msp.json`/`jetson_rc.json` build and
  honour the **Betaflight AETR** channel order — pins the throttle/yaw bug found on the bench),
  plus pilot-lifecycle-through-the-loop and round-robin→CoT-XML regressions in `test_rc.py`.
  Suite is **233 tests at 100% line+branch**; `mypy --strict` + `ruff` clean.

## [0.4.0] - 2026-06-07

Bring a real **Betaflight flight controller over USB** all the way to an ATAK track,
including a GPS-less bench FC. Additive and backward-compatible — no `Envelope` shape
change, `SCHEMA_VERSION` stays `1`; the new `remarks` payload key is optional and a
config that omits the `fallback_*`/`remarks` features behaves exactly as before.

### Added
- **`msp_source` fixed-position fallback** — `fallback_lat`, `fallback_lon`,
  `fallback_hae` options. When the FC has no GPS fix and a fallback is set, the FC still
  appears as a stationary track (a GPS fix, when present, always wins). With no fix and
  no fallback, nothing is emitted — the original behaviour.
- **MSP telemetry remarks** — `_default_poll` now also reads `MSP_ANALOG`
  (battery voltage, current, RSSI) and `MSP_ATTITUDE` (roll/pitch/yaw); the transport
  renders the present fields into an optional `remarks` string. The `telemetry` and
  `cot` codecs carry `remarks` through (payload root → CoT `<detail><remarks>`), with
  round-trip on decode. Enrichment reads are isolated so a slow/absent MSP message
  degrades to "no remarks" rather than dropping the position.
- **Ops:** `flightctl/configs/jetson_gateway.msp.json` (Betaflight-over-USB gateway
  config) and an `FC_MODE=msp` mode in `flightctl/scripts/start_all.sh` that polls the
  FC directly and skips the MAVLink-only services (sim/mavp2p/mavlink2rest).

## [0.3.0] - 2026-06-06

Additive, backward-compatible hardening of the CoT/TAK link. No `Envelope` shape
change — `SCHEMA_VERSION` stays `1`; both features are off by default, so a node that
omits the new options behaves byte-for-byte as in 0.2.0.

### Added
- **TLS CoT for the `tak_tcp` transport** (typically FreeTAKServer `:8089`).
  Config-driven options on the transport: `tls`, `tls_cafile`, `tls_certfile`,
  `tls_keyfile`, `tls_verify`, `tls_check_hostname`, `tls_server_hostname`. The SSL
  context is built via a pure `_build_ssl_context` helper (covered by tests) and the
  context is validated at construction time (fail-fast on a bad/missing cert); the
  real socket builder is the only added `# pragma: no cover`. An injected `connector`
  still overrides everything. Plain `:8087` is unchanged when `tls=False`.
- **FTS rate-limit pacing** — `meshsa.pacing.Pacer`, an inline minimum-hold pacer
  (PyTAK `FTS_COMPAT` contract) so a fast telemetry source does not overrun a
  rate-limited FreeTAKServer. Enable per transport with `pace_min_interval_s`
  (`0` = disabled, the default). `clock` is injectable for testing.
- **Ops:** `flightctl/scripts/gen_certs.sh` (CA + server + client certs and an ATAK
  data-package template), `flightctl/configs/jetson_gateway.tls.json` (TLS + pacing
  example on `:8089`), and a TLS pointer in `flightctl/systemd/fts.env.example`.
- `trustme` added to the `[dev]` extra for hermetic in-test TLS cert generation.

### Changed
- `SleepFn` is now defined once in `meshsa.protocols` (was duplicated in the TAK and
  Meshtastic transports).

## [0.2.0] - 2026-06-06

### Added
- **Stack orchestration + browser UIs (ops).**
  - `flightctl/scripts/start_all.sh` — one-command `start`/`stop`/`status`/`restart`
    that brings the whole edge node up in dependency order (FreeTAKServer → FTS Web UI
    → WebMap → meshsa gateway → mavlink2rest → mavp2p → simulator) with a per-service
    readiness wait. Encodes two hard constraints: (1) `udpc` consumers must bind before
    mavp2p connects (else its connected-UDP socket latches `ECONNREFUSED`), and (2) the
    simulator emits MAVLink **v2** (`MAVLINK20=1`) because mavlink2rest ignores v1.
  - `flightctl/configs/jetson_gateway.proxy.json` — gateway behind the proxy
    (`mavlink_source` on `udpin:127.0.0.1:14551`) so mavp2p can fan one autopilot
    stream to the gateway, mavlink2rest, and any GCS.
  - Browser UIs wired in: FreeTAKServer Web UI (`:5000`), FreeTAKHub **WebMap** Node-RED
    flow (`:1880/tak-map/`), and **mavlink2rest** (`:8088`) as the in-browser MAVLink GCS
    (QGroundControl is x86_64-only on arm64; MAVProxy's wx GUI needs apt/sudo).
- **Flight-control telemetry integration (backward-compatible, no schema bump).**
  - `telemetry` codec (`meshsa.telemetry.TelemetryCodec`): stateless map from a
    structured telemetry frame to a `PLI` `Envelope` (and back). Registered as
    `"telemetry"`.
  - `mavlink_source` transport (`meshsa.transports.MavlinkSourceTransport`):
    receive-only MAVLink source that parses `GLOBAL_POSITION_INT` in a reader
    thread (injectable pymavlink connection; real link builder `# pragma: no cover`)
    and ingests one telemetry frame per fix via the shared drop-counting inbox —
    same threading pattern as the Meshtastic transport. Each fix gets a unique
    `msg_id` so the router's dedupe does not collapse a track.
  - `msp_source` transport (`meshsa.transports.MspSourceTransport`): receive-only
    Betaflight **MSP** (YAMSPy) source — polls GPS fixes on a reader thread (injectable
    board + `poll`; real YAMSPy glue `# pragma: no cover`) and reuses the `telemetry`
    codec. Configurable coordinate/altitude scaling (MSP units vary by firmware).
  - Drone/UAS tracks reach ATAK as **air** CoT by configuring a per-transport
    `cot` codec instance with an air `pli_type` via `codec_options` — no new
    `MessageKind`, no `schema_version` change. A source-omitted node is byte-for-byte
    the previous mesh node.
  - `[mavlink]` (`pymavlink`) and `[msp]` (`yamspy`) optional extras; both verified
    to install and import on aarch64 / JetPack 6.
  - Tests: `test_telemetry_codec.py`, `test_mavlink_source.py`, `test_msp_source.py`,
    and `test_mavlink_bridge_e2e.py` (config-driven MAVLink-fix → CoT-air-track bridge,
    no network). Suite is **163 passing, 100% line+branch coverage**; mypy `--strict`
    clean (`pymavlink.*`, `yamspy.*` added to the missing-imports override). A live
    pymavlink-over-UDP smoke run confirmed the end-to-end source→telemetry→CoT-air path.
- `flightctl/` ops area: SSD-relocation script, an FTS setup script, `mavp2p`/
  `freetakserver`/`meshsa-gateway` systemd units + env examples, a stable-serial udev
  rule, an example gateway config, a config-driven `run_gateway.py`, and a
  `mavlink_fake.py` simulator.
- **Manually verified on-device** (not part of the automated suite, which asserts the
  bridge via loopback): a simulated MAVLink fix flowed `mavlink_source` → `telemetry`
  → `tak_tcp`/`cot` → a **live FreeTAKServer** on `:8087` → an ATAK-style viewer client,
  which received the **air** track (`a-f-A-M-F-Q`, `uid=uav-1`).
  `flightctl/scripts/setup_fts.sh` captures the FTS dependency pins
  required to boot on Python 3.11 / aarch64 (`setuptools<81` for `pkg_resources`,
  the undeclared `requests`, and `opentelemetry==1.20.0` for digitalpy compatibility).

- `[dev]` extra (pytest, coverage, ruff, mypy, pre-commit, build, twine).
- `LICENSE` (Apache-2.0), `CHANGELOG.md`, `CONTRIBUTING.md`,
  `CODE_OF_CONDUCT.md`, `SECURITY.md`.
- `py.typed` marker (PEP 561) so downstream consumers get `meshsa`'s types;
  packaged via `[tool.setuptools.package-data]`.
- Per-codec `supported_schemas` (`frozenset[int]`): codecs accept the full
  compatibility window by default (`version.SUPPORTED_SCHEMAS`) but can be built
  with an explicit set so multiple codec/schema versions can coexist on one node.
  `JsonCodec`/`CompactCodec` gate decode on membership; `CotCodec` is
  schema-agnostic (CoT XML carries no meshsa schema). Additive and
  behavior-preserving — no `SCHEMA_VERSION` bump.
- Observability: `Router.metrics` (`RouterMetrics`: rx, tx, forwarded,
  dropped_undecodable, schema_mismatch — the last two split via a dedicated
  `IncompatibleSchemaError` branch in the pump) and per-transport `reconnects`
  counters on the Meshtastic and TAK-TCP supervisors.
- `meshsa.health.health_snapshot(node)` (pure, JSON-able status + metrics) and an
  opt-in `/healthz` aiohttp listener (`serve_healthz`) behind a new `[health]`
  extra; `aiohttp` is imported lazily so the module loads without it.
- `HealthConfig` (`NodeConfig.health`: enabled/host/port).
- Hypothesis property tests for codec round-trips (JSON lossless; Compact PLI
  within scale tolerance; Compact CHAT text preserved) — `hypothesis` added to `[dev]`.
- Serialized-envelope snapshot tests (`tests/snapshots/`) for JSON/Compact/CoT of a
  pinned canonical envelope, to catch accidental wire-format breakage
  (regenerate with `MESHSA_UPDATE_SNAPSHOTS=1`).
- Transport-level multicast group join/leave test for `TakMulticastTransport`.
- Opt-in out-of-tree plugin discovery: `meshsa.plugins.load_plugins()` loads the
  `meshsa.transports` / `meshsa.codecs` entry-point groups (py3.10–3.12 metadata
  compat shim), skipping any broken driver. Not called implicitly.
- `build_node(codec_instances=...)` injects a pre-configured `Codec` instance per
  transport (preferred over registry-by-name), closing the audit's modularity gap
  where a codec could only be referenced by name.
- `meshsa.version.warn_deprecated(old, replacement, removed_in=...)` helper to emit
  `DeprecationWarning` on renamed fields/options, per the compatibility policy.
- `.github/workflows/nightly.yml`: scheduled run that installs the full extras
  (`[dev,meshtastic,health]`) and runs mypy + the suite against the real optional
  dependency graph (catching optional-dep typing drift the `[dev]`-only CI can't),
  plus any `@pytest.mark.slow` soak tests. Registered the `slow` pytest marker.
- `release.yml`: opt-in GHCR image publish on `v*` tags (gated on the
  `PUBLISH_DOCKER` repo variable, using the built-in `GITHUB_TOKEN`).
- Docker runtime image now installs the `[meshtastic,health]` extras.
- `docs/ARCHITECTURE.md`, `docs/AUDIT_REPORT.md`.
- `.github/workflows/ci.yml` (matrix py3.10/3.11/3.12), `.github/workflows/release.yml`.
- `.pre-commit-config.yaml`, `tools/Dockerfile`, `tools/Makefile`.
- Config-driven bridge e2e coverage for JSON mesh <-> CoT TAK translation through
  `NodeConfig` and `build_node`.
- Enterprise agent harness: `AGENTS.md`, `CLAUDE.md`, Copilot instructions,
  scoped folder guidance, custom agent modes, and project skills.

### Changed
- Repository reorganized into enterprise layout: `packages/`, `ops/`, `hardware/`,
  `docs/`, `tools/`, `.github/`, `archive/`.
- 22 duplicated root files removed (canonical copies live in their domain
  subfolders); ZIP snapshots moved to `archive/`.
- `meshsa` package now lives at `packages/meshsa/` (was `meshsa_framework/meshsa/`).
- `examples/base_node.py` moved into the importable package at
  `src/meshsa/examples/base_node.py` and exposed as the `meshsa-base` console script.
- `meshsa-base.service` updated to call `meshsa-base` and use `KillSignal=SIGINT`.
- Runtime dependencies pinned with upper bounds (`pydantic>=2,<3`, `structlog>=23,<26`).
- `meshtastic` and `pypubsub` moved to the `[meshtastic]` optional extra.
- CI now runs strict mypy as a required package-local check.
- Type hints tightened across codecs, registry, router, node assembly, transports,
  and the base-node example without changing runtime behavior.
- Re-enabled the `SIM105` ruff rule and rewrote the 7 `try/except: pass` sites as
  `contextlib.suppress(...)`; the rule is no longer ignored.
- Confirmed the project license as Apache-2.0 (dropped the "placeholder" wording).
- Moved the runnable CLI from `examples/base_node.py` into the importable
  `meshsa.cli` module (the example is now a thin re-export so `examples/` stays
  demonstrative-only); the `meshsa-base` console script targets `meshsa.cli:main`
  (name unchanged, so the systemd unit is unaffected). Added
  `--health/--healthz-host/--healthz-port` flags.

### Fixed
- `RouterConfig.queue_maxsize` is now applied to transport inbox queues (was
  dead config); a per-transport `options.queue_maxsize` still overrides it.
- `MeshConfig` is now threaded to the Meshtastic transport (was dead config) and
  applied to the device via an injectable provisioning seam, on the initial
  connect **and re-applied after every reconnect**. Scope: the default
  provisioner applies `region` (passthrough) and persists it; `channel`/`psk`/
  `freq_khz` are logged as pending firmware-specific implementation rather than
  silently claimed. The control flow is fully unit-tested with a fake device.
- Transport inbox is now bounded and non-blocking across **all** inbound paths
  (including the Meshtastic receive callback): when full it drops the newest
  frame and counts it (`dropped_inbox_full`) instead of stalling the reader —
  relevant now that `queue_maxsize` is configurable.
- `_default_pubsub()` return typing corrected (cast) so strict mypy passes with
  the `[meshtastic]` extra installed, not only in the `[dev]`-only CI env.
- De-duplicated the `9999999.0` CoT/error sentinel into a shared
  `meshsa.models.UNKNOWN_ERROR_M` used by both the model and the CoT codec.

## [0.1.0] - 2026-06-02

### Added
- Initial framework release: schema-versioned `Envelope`, registry-based codec and
  transport plug-in points, async `Router` with per-transport codec selection and
  message dedupe, JSON / CoT / compact codecs, Loopback / Meshtastic / TAK transports.
- 98-test suite, 100% line + branch coverage.
