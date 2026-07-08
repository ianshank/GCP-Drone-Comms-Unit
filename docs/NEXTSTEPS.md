# Next Steps — GCP-Drone-Comms-Unit

> Changeable, near-term backlog. The stable plan is [CHARTER.md](CHARTER.md) (scope +
> invariants) and [ROADMAP.md](ROADMAP.md) (milestone trajectory); keep this aligned with
> both. Update freely as work lands.
>
> ℹ️ An externally-circulated "Architectural Roadmap" (Google Cloud / Langfuse / Spring Boot /
> agent-swarm) was reconciled against the real code in
> [ROADMAP_RECONCILIATION.md](ROADMAP_RECONCILIATION.md) — most of it is inapplicable or out of
> scope per CHARTER §3; the in-scope slice became the AI-inference Track-B work below.

## Done (this initial PR)
- `telemetry` codec + `mavlink_source` (pymavlink) + `msp_source` (Betaflight MSP/YAMSPy)
  transports; drone/FC fixes → **air** CoT tracks with no schema bump.
- Config-driven gateway (`flightctl/run_gateway.py` + `configs/jetson_gateway.json`),
  MAVLink simulator, systemd units, FTS setup, SSD-relocation tooling.
- `--log-level` / `MESHSA_LOG_LEVEL`; 165 tests at 100% line+branch; mypy `--strict` + ruff clean.
- Manually verified on-device: fake MAVLink → gateway → live FreeTAKServer `:8087` → ATAK
  viewer received the air track.

## AI Inference (initiative E — `meshsa.inference`)
> Optional NVIDIA Nemotron NIM AI bridge: subscribes to mesh traffic → tactical analysis →
> `[AI Insight]` summaries back on the mesh. Install with `meshsa[inference]`. Config via
> `MESHSA_INFERENCE_*` env vars (12 fields incl. `backoff_base`, `insight_prefix`). Hardened:
> lazy aiohttp, session reuse with `asyncio.Lock`, feedback-loop prevention, configurable
> backoff, lifecycle guards, injectable sleep for testability. 780 tests at 99.48% cov.

- [x] **MVP**: `NemotronClient` + `InferenceService` + `NemotronConfig` + `InferenceResult`
- [x] **Env-var bindings**: 12 `MESHSA_INFERENCE_*` vars in `NodeConfig.from_env()` (incl.
      `backoff_base`, `insight_prefix`)
- [x] **Hardening**: lazy aiohttp import, `_require_aiohttp()` guard, session reuse with
      `asyncio.Lock`, feedback-loop filter (configurable `insight_prefix`), lifecycle flags,
      API key warning, configurable backoff via `backoff_base`, injectable `sleep`
- [x] **CI**: `meshsa[dev,inference]` install, 30 inference tests (fakes-only)
- [x] **Version-robust test gate (Track 0.1)**: the HTTP boundary is now an injectable
      `HttpTransport` `Protocol` (`HttpResponse` + default `AiohttpTransport`); unit tests use a
      pure `FakeHttpTransport` (no `aiohttp`/sockets), so the suite no longer breaks on `aiohttp`
      version drift. The brittle `aiohttp<3.10` pin and `aioresponses` were removed; persistent
      non-2xx → `InferenceHttpError`, transport/timeout → `InferenceTransportError`.
      Spec: [specs/initiative-e-inference.md](specs/initiative-e-inference.md). `inference.py` 100% cov.
- [x] **Local rate limiting**: `min_interval_s` + `max_concurrent_requests` (`NemotronConfig`,
      `MESHSA_INFERENCE_*`). Enforced in `InferenceService` — a `BoundedSemaphore` caps
      concurrency and a clock-driven min-interval gate caps rate (a semaphore alone cannot).
      Both default to 0 (no-op). Deliberately bounds in-flight *inclusive of retries* to cap
      edge API spend (documented in the spec).
- [x] **Structured response parsing**: `response_format` (`text`|`json`) + `guided_json_schema`.
      Per NVIDIA guidance, a schema is sent as `nvext.guided_json` (preferred over the portable
      `response_format:{"type":"json_object"}` toggle, which allows empty JSON); `_parse` unwraps a
      JSON `summary` field and **falls back to raw text** on any non-JSON reply, so the text path
      never regresses.
- [x] **Multi-model support**: `models` allow-list (`MESHSA_INFERENCE_MODELS`, comma-separated) +
      `NemotronConfig.with_model()` runtime switch that rejects a model outside the allow-list; a
      validator enforces `model ∈ models` at construction.
- [x] **Offline fallback**: bounded `offline_queue_max` deque in `InferenceService` — a failure
      (transport/HTTP error surviving retries) enqueues the envelope (drop-and-count on overflow,
      mirroring `FlightLogger`) and the next success drains/replays it. 0 = disabled (prior behavior).
- [x] **`/metrics` counters + task-intake backpressure**: `InferenceService.as_dict()` exposes
      `offline_dropped`/`offline_queue_depth`/`intake_dropped`/`pending_tasks`; a matching
      `meshsa_inference_*` Prometheus/JSON series is emitted via `render_prometheus`/
      `health.render_metrics` when `node.inference_service` is set, with a Grafana "AI Inference"
      row. New `max_pending_tasks` (`MESHSA_INFERENCE_MAX_PENDING_TASKS`, default `0` = unbounded)
      bounds task intake with drop-and-count, mirroring the offline-queue pattern.

## Perception (initiative D — **CHARTER carve-out ratified 2026-06-20**)
> On-board `jetson_yolo_gcs`: camera → YOLO/Hailo detection → GStreamer video to a GCS →
> opt-in MAVLink `LANDING_TARGET`. Self-contained (no meshsa runtime dep). MVP shipped in
> PR #20 (hardened: ruff/mypy-strict, ~98% cov). Target hardware: **Orin Nano + Hailo-8**;
> support **both ArduPilot and PX4**.
>
> ⚠️ **Current safety posture:** `LANDING_TARGET` is advisory and **off by default**
> (`MAVLINK_ENABLE_LANDING_TARGET=false`). Today there is **no autopilot-heartbeat gate and
> no cadence floor** — the operator owns that risk until the hardening items below land.

- [x] **MVP + hardening** (PR #20): detection factory (ext→backend), pure GStreamer pipeline
      builders, pymavlink `LANDING_TARGET` bridge, DI pipeline with path-specific error policy
      (detect=drop-and-count, egress=best-effort, **publish=fail-loud**), `--health-check`.
- [x] **Deploy glue** (this iteration): `flightctl/systemd/jetson-yolo-gcs.service` + deploy
      note; pipeline runtime counters + **liveness** snapshot (`fps` ≠ liveness during a stall).
- [x] **Detection → CoT MARKER bridge (Phase A, meshsa side):** a separate detector process
      sends one JSON detection frame per object over UDP to the new `detection_ingest` source
      transport; the new `detection` codec maps it to a `MessageKind.MARKER` Envelope and
      `CotCodec` gained a real MARKER encode path (configurable `marker_type`, class+confidence
      in `<contact>`/`<remarks>`). `meshsa.cv.geo` does the pure pixel→ground projection. Config:
      `flightctl/configs/jetson_gateway.yolo.json`. Hardware-free + fully tested. **Remaining:**
      the DeepStream/YOLO11 device pieces (install, FP16 engine, pyds probe) — later phases.
- [ ] **Real Hailo-8 `.hef` inference** (preferred offload; TensorRT GPU is the fallback).
      `.pt`→ONNX→`.hef` is built on an **x86 Ubuntu host only** (Hailo DFC is not ARM); the
      `.hef` is an offline artifact. Add a `[hailo]` extra + model-prep note.
- [x] **PX4 `LOCAL_NED` dialect (software-complete; HW validation pending):** `MAVLINK_FRAME`
      (`body_frd` default | `local_ned`) frame-dispatches `LandingTargetBridge.publish`; the
      `local_ned` path projects pixel→bearing→NED (new `geometry/ned.py` pure ray-cast +
      `mavlink/pose.py` `PoseSource`/`MavlinkPoseSource`, FOV + attitude/alt) and sends PX4's
      expected x/y/z with `position_valid=1`. Body-FRD wire output stays byte-identical
      (pin-guarded). **Fail-safe**, not fail-open: suppresses (returns `False`, no send) without a
      `PoseSource`, without a fresh pose, or on an unprojectable/degenerate ray — reason-keyed via
      `suppressed_snapshot()` (`no_heartbeat`/`no_pose`/`unprojectable`). **Remaining:** on-vehicle
      PX4 SITL/hardware validation of the NED path.
      ([landing_target](https://mavlink.io/en/services/landing_target.html) /
      [PX4 precland](https://docs.px4.io/main/en/advanced_features/precland.html))
- [x] **TIMESYNC + capture-time `time_usec` (software-complete; HW validation pending):** new
      `mavlink/timesync.py` `TimeSync` (offset tracking + `to_vehicle_usec`) gated by
      `MAVLINK_TIMESYNC_ENABLED` (default `false`, load-bearing) and `MAVLINK_CAPTURE_TIME_SOURCE`
      (`publish` default | `capture`). Defaults preserve current publish-time behavior; the device
      TIMESYNC round-trip exchange itself is hardware-only (deferred, `# pragma: no cover`).
      **Remaining:** on-vehicle validation of the offset/capture-time path.
      ([TIMESYNC](https://mavlink.io/en/services/timesync.html))
- [x] **Precision-landing safety hardening (software; HW validation still pending):**
      autopilot-**heartbeat** gate shipped — a self-contained `mavlink/heartbeat.py`
      `HeartbeatMonitor` mirrors the `meshsa.command.health.HeartbeatHealth` fail-closed pattern;
      `LandingTargetBridge.publish` suppresses (returns `False`, no send) until a fresh autopilot
      HEARTBEAT is polled (`poll_heartbeat`, filtered by `target_system`/`target_component`). The
      pipeline now **counts + escalates** publish failures (`PIPELINE_PUBLISH_FAILURE_TOLERANCE`,
      default 3) instead of crashing the camera+stream loop, and counts **cadence-floor**
      violations against `MAVLINK_MIN_PUBLISH_RATE_HZ` (default 10). Config: `MAVLINK_REQUIRE_HEARTBEAT`
      (default true), `MAVLINK_HEARTBEAT_TIMEOUT_S` (default 2 s = ArduPilot `LANDING_TARGET_TIMEOUT_MS`).
      **Remaining:** CHARTER wording (advisory hint, but **authoritative for final approach** once
      the operator enables precision landing) + `PLND_STRICT` failsafe note; and on-vehicle HW
      validation of the gate. Note: the gate needs a **bidirectional** endpoint (`udp:`/`udpin:`),
      not the send-only `udpout:` default.
- [ ] **On-device runbook:** TensorRT `.engine` export (FP16; INT8 `imgsz=320,batch=1,workspace=1`
      on JetPack 6); realistic **~30–40 FPS YOLOv8n FP16 @640 on Orin Nano** (60 FPS is NX/INT8);
      `nvv4l2` NVMM-caps smoke (NX/AGX); QGroundControl RTP smoke (`udp:5600`, `pt=96`).
- [ ] **Live `/healthz` + watchdog:** optional `[health]` aiohttp listener (lazy in-function
      import, mirroring `meshsa.health`); wire liveness → systemd `WatchdogSec`/`sd_notify`.
- [x] **Tighten coverage** on the safety files `pipeline.py` + `mavlink/bridge.py` +
      `mavlink/heartbeat.py` — the heartbeat gate, suppression, poll accept/ignore/wildcard/read-error,
      failure-tolerance escalation, and cadence-violation paths are all covered fakes-only
      (`tests/unit/test_mavlink_heartbeat.py`, `test_mavlink_bridge.py`, `tests/integration/test_pipeline_mock.py`).
- [ ] **(Longer, M3)** detections → `cot` codec sensor PoI/FoV (needs pixel→geo / camera pose).

## GCS commanding (initiative — **CHARTER carve-out ratified 2026-06-16**)
> Two-way vehicle commanding is now an authorized but **bounded** scope per the
> [CHARTER.md](CHARTER.md) §3 supervised-commanding carve-out (ratified 2026-06-16). The
> MAVLink plumbing is the easy part; the work is the safety/auth/audit layer. Sequence this
> **after** M2 hardening — do not ship a command surface before TLS + auth land.
>
> **⚠️ Status (2026-06-30): the command stack is IMPLEMENTED and unit-tested** — `meshsa.command.*`
> (commands/config/safety/audit/health/lifecycle/mavlink_link/mavlink_pump/service/errors) + nine
> `tests/test_command_*.py` + `flightctl/run_commander.py`. The design adopted the standalone
> **supervised service** structure (`run_commander.py`), not the registry-`mavlink_sink` seam (see
> the design doc §10 amendment). **The M2-gate clearance is a maintainer decision** — see
> [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) Track E.
- [x] **Scope ratified** in [CHARTER.md](CHARTER.md) (2026-06-16): whitelist safe commands first
      (SET_MODE, RTL) before destructive ones (force-disarm). Maintainer sign-off recorded.
- [x] **Command path (standalone service, not registry seam):** `flightctl/run_commander.py`
      owns a pymavlink link; `COMMAND_INT`/`COMMAND_LONG` packing in `command/mavlink_link.py`,
      ACK/retry state machine in `command/lifecycle.py` with bounded retries + fail-closed.
      (Design §10 documents why the `mavlink_sink` registry seam did not hold for MAVLink.)
- [x] **Safety layer:** operator-confirmation gate (`command/safety.py` `ConfirmationGate`),
      `MESHSA_CMD_TOKEN` bearer auth + loopback-default bind (`run_commander.py`), append-only
      fsync-durable audit log (`command/audit.py` `JsonlAuditLog`), and `arm_allowed()` +
      `HeartbeatHealth` preconditions. `MAV_CMD_COMPONENT_ARM_DISARM` param2=`21196` force path is
      off by default behind a **separate** force confirmation. **Remaining (Track E):** audit-soak
      under sustained overflow; confirm whitelist defaults; review off-loopback bind vs M2 TLS.
      ([ArduPilot](https://ardupilot.org/dev/docs/mavlink-arming-and-disarming.html))
- [ ] ⚠️ `mavlink2rest` on `:8088` is a bidirectional command surface with **no
      built-in auth or interlock** ([mavlink2rest](https://github.com/mavlink/mavlink2rest));
      MAVSDK acks signal *intent, not completion*
      ([MAVSDK](https://mavsdk.mavlink.io/main/en/cpp/guide/taking_off_landing.html)).
- [ ] Keep `meshsa.llm` **read-only by default**; any future command tool must be
      gated behind explicit human confirmation, never autonomous model issuance.

## Near-term (M2 hardening)
- [x] **Hardware-free FTS e2e harness:** `packages/meshsa/tests/e2e/test_fts_e2e.py` — CotCodec
      encode→decode round-trip + CotFramer split-stream reassembly, always run (no hardware, adds
      coverage); `e2e` marker registered in pyproject.
- [ ] **Automated FTS e2e** (non-coverage job): bring up FTS in CI on a self-hosted Jetson
      runner; assert a track via the FTS REST API and a multicast CoT listener. A live-FTS
      roundtrip test and `.github/workflows/fts-e2e.yml` (`workflow_dispatch`-only,
      `runs-on: [self-hosted, jetson, arm64]`) are already wired behind `MESHSA_FTS_E2E=1`, but the
      workflow does not run in normal CI pending a registered self-hosted Jetson runner.
- [x] **TLS CoT (`:8089`)** for the TAK TCP transport (shipped — `transports/tak.py`:
      `tls://`/`ssl://`/`tcp://` scheme parsing, `_build_ssl_context`, CA + client cert/key,
      8089 default; plain `:8087` kept for closed dev nets). **Remaining:** signed ATAK
      data-package / `AtakOfTheCerts`-style CA→server→per-user PKI generation + client-import doc.
- [x] **Pacing / rate-limit** to FTS (shipped — `transports/pacing.py`, 100% cov) so fast
      tracks aren't dropped ([PyTAK](https://github.com/snstac/pytak)).
- [x] **Transport observability:** shipped — per-transport `rx_frames` + throttled `"source rx"`
      link-state log on `PollingSourceTransport`; `dropped_inbox_full` surfaced per transport;
      `RouterMetrics.as_dict()` + `meshsa.render_prometheus` export (Prometheus/JSON) on an
      opt-in `/metrics` route. The **Grafana golden-signal dashboard** (plan Track A.1) also
      shipped — `ops/observability/grafana-meshsa-dashboard.json` + README map
      `rx/tx/forwarded/dropped/reconnects` to the four signals
      ([Google SRE](https://sre.google/sre-book/monitoring-distributed-systems/)), with a
      series-drift guard in `test_metrics.py::test_render_prometheus_emits_all_dashboard_metric_names`.
      **Remaining:** if ever multi-process, set & **wipe `PROMETHEUS_MULTIPROC_DIR` between runs**
      ([client_python](http://prometheus.github.io/client_python/multiprocess/)).
- [x] **Pin FTS deps** in a constraints file (`flightctl/constraints/fts-constraints.txt`:
      `setuptools<81`, `requests`, `opentelemetry==1.20.0`) so `setup_fts.sh` is reproducible.

## Mid-term (M3 richer tracks)
- [x] Course/speed/battery/attitude as **additive `payload` keys** + a CoT detail-aware
      codec (no `MessageKind` change; `schema_version` unchanged). Shipped (M3.1):
      `Position.course_deg/speed_ms`, `Attitude`, `Telemetry.battery_v/attitude` in
      `models.py`; `CotCodec` `_emit_richer_detail` (track/status/vendor/attitude children,
      `emit_detail` opt-out) with round-trip decode in `cot.py`.
- [ ] Sensor Point-of-Interest / field-of-view CoT; multiple simultaneous UAS with stable UIDs.
      Implement SPI/FOV **natively in the `cot` codec** — do not depend on FreeTAKUAS
      ([abandoned since 2022](https://github.com/FreeTAKTeam/FreeTAKUAS)).
- [ ] Betaflight ≥2025.12 MAVLink-on-UART path (reuse `mavlink_source`); MSP attitude/altitude.
      Note Betaflight 2025.12+ also speaks **MAVLink over the ExpressLRS link**
      ([Betaflight wiki](https://betaflight.com/docs/wiki/guides/current/MAVLinkELRS) /
      [ExpressLRS](https://www.expresslrs.org/software/mavlink/)) — consolidating on
      MAVLink-over-ELRS could retire the bespoke CRSF GPS decode. Track [mLRS](https://github.com/olliw42/mLRS).
- [ ] Optional **Remote ID → CoT** ingest via a `DroneCOT`-style transport
      ([DroneCOT](https://github.com/snstac/dronecot)) for ODID/DJI DroneID situational awareness.

## FPV ground-side subsystem (`meshsa.fpv`)
Implemented greenfield (Phase 0 Errata E1 + Phase 1 Spec v1.1); see
[docs/specs/](specs/) and the ARCHITECTURE section. Status:
- [x] CRSF parsers, CRC framing, echo-suppressed `CrsfLink`, address prober (E1.2/E1.3).
- [x] Telemetry store + co-signal link-health monitor (hysteresis, version-keyed floors).
- [x] Flight logger (writer thread, drop-and-count, versioned manifest + JSONL headers).
- [x] `ArmGuard` pre-flight interlock + CHARTER §3 carve-out.
- [x] `fpv-telemetry-monitor` / `fpv-log-replay` / `fpv-log-convert`; 100% module coverage.
- [x] **Human sign-off on the CHARTER §3 carve-out** (RC-TX scope expansion) — ratified 2026-06-12.
- [ ] Bench validation (§8): live LinkStats on hardware, voltage calibration, ratio sweep,
      antenna-removal transitions, `!FS!` end-to-end — thresholds remain provisional until then.
- [x] Phase 2: camera wired into the existing `frames.jsonl`/`video` stub via a `CaptureWriter`
      daemon (`fpv/camera.py`) reading an injected `CameraSource` — additive, `DATASET_SCHEMA`
      stays 2; only the capture backend is `# pragma: no cover` glue (shipped, see ARCHITECTURE).
- [x] Additive `crsf_source` transport so CRSF telemetry becomes an ATAK air track (0.3.0;
      decodes GPS 0x02 → `GpsSensor` → `telemetry` codec; `DATASET_SCHEMA` 1 → 2).

## Ops / packaging (M4–M5)
- [ ] systemd enablement with a dedicated `flightctl` service user + correct ownership of the
      SSD venvs (currently proven via manual run).
- [ ] Betaflight Configurator: confirm Chromium PWA path on the unit; document source build.
- [ ] Optional **root-on-NVMe** appliance build to remove the eMMC constraint entirely.
- [ ] Reproducible multi-arch image; signed releases; GHCR publish on tags (workflow exists).
- [ ] Fleet resilience: **Meshtastic store-and-forward** for intermittent links
      ([S&F module](https://meshtastic.org/docs/configuration/module/store-and-forward-module/)).

## Code-quality backlog (2026-06-21 gap scan)
Found by automated gap analysis (source code + test coverage subagents); lint,
`mypy --strict`, format, and the test suite are all green — these are deferred design items.
- [x] **[config] `HealthConfig` + `RouterConfig` missing env-var bindings** (`config.py`).
      Fixed: `MESHSA_HEALTH_*` and `MESHSA_ROUTER_*` bindings added in `NodeConfig.from_env()`.
- [x] **[robustness] `NemotronClient._session` race condition** (`inference.py`). Fixed:
      `asyncio.Lock` guards all `_session` access (creation, use, close).
- [x] **[robustness] Router subscriber exception crashes pump** (`router.py`). Fixed:
      subscriber calls wrapped in `try/except` with `exc_info=True` logging.
- [x] **[consistency] `CommandError` disconnected from `MeshSAError` hierarchy**
      (`command/errors.py`). Fixed: now inherits `MeshSAError`.
- [x] **[config] Hardcoded AI insight prefix and backoff base** (`inference.py`). Fixed:
      `insight_prefix` and `backoff_base` are now configurable `NemotronConfig` fields with
      env-var bindings.
- [x] **[logging] Missing `exc_info=True` on exception warnings** (`router.py`, `inference.py`).
      Fixed: tracebacks are now preserved in structured logs.
- [x] **[security] `meshsa.llm` server bound `0.0.0.0` with no auth** (`llm/server.py`). Fixed:
      `DEFAULT_HOST` is now `127.0.0.1`, a `MESHSA_LLM_TOKEN` bearer check gates `/chat`, and the
      server **fails closed** (refuses to start) on a non-loopback bind without a token.
- [x] **[robustness] `TakMulticastTransport._recv_loop` had no error recovery** (`transports/tak.py`).
      Fixed: the recv loop now closes the wedged socket, rebuilds via the factory, and backs off.
- [x] **[consistency] `FlightLogger.dropped_records` omits the `"events"`/`"frames"` keys**
      (`fpv/flight_logger.py`). Verified fixed (2026-07-08 reconciliation): `dropped_records` is
      seeded via `dict.fromkeys(_HEADERS, 0)`, so all four streams (rc/telemetry/events/frames)
      carry a `0` in the manifest.
- [x] **[consistency] Duplicate `MonotonicClock` classes** (`protocols.py` vs `fpv/protocols.py`);
      deduplicate by importing the framework-level `MonotonicClock` in the FPV subsystem.
- [x] **[config] `FpvSettings` and `CommanderConfig` lack `from_env()` with individual bindings**
      — operators must use the JSON blob for non-`sessions_root` fields.
- [x] **[DI] `FlightLogger._writer()` calls `time.monotonic()` directly** instead of the injected
      `Clock` — flush-interval timing is untestable via `FakeClock`.
- [x] **[config] `llm/server.py` `MAX_PROMPT_CHARS` and `llm/agent.py` `DEFAULT_MAX_TOKENS`/
      `DEFAULT_MAX_ITERATIONS`** have no env-var bindings.
- [ ] **[robustness] guard unguarded teardown/parse paths:** `camera.py close()` source close,
      `fpv/tools/replay.py` `rec[...]` KeyErrors, `mavlink_source` attribute assumptions.

### M2 auth-audit findings (2026-07-08 — see [AUDIT_M2_AUTH.md](AUDIT_M2_AUTH.md))
Full evidence-backed enumeration of all 16 network-facing surfaces and their auth/encryption
posture (the Track 0.2 / E.3 prerequisite before the maintainer rules on the commanding M2 gate).
- [x] **[security] `/healthz`+`/metrics` was the one fail-open aiohttp surface** (`health.py`).
      Fixed: `HealthConfig.token` (`MESHSA_HEALTH_TOKEN`) + `validate_healthz_bind` refuse a
      non-loopback bind without a token (validated before `node.start()`), and `/metrics` is
      bearer-gated. Default (loopback, no token) unchanged. Auth branch lives in the testable
      `build_healthz_app` factory (`TestClient`-covered), not the pragma'd socket wiring.
- [ ] **[security] no bind guard on UDP ingest transports** — `detection_ingest` (UDP 8099) and
      `mavlink_source` (`udpin:14550`) fail open on a non-loopback `host`/`endpoint` override
      (no `validate_bind`). Loopback default is the current mitigation.
- [ ] **[consistency] Meshtastic PSK provisioning is aspirational in code** — `_default_provisioner`
      applies only the LoRa `region` and logs channel/psk/freq as unset (`meshtastic_radio.py:81-86`).
      Either implement PSK provisioning or downgrade the docs/config so operators don't assume an
      enforced PSK. **Maintainer decision** (touches deploy expectations).
- [ ] **[cleanup] shared default port `8099`** between `detection_ingest` (UDP) and the scout
      station (TCP) — not an OS-level collision, but a confusing default; deconflict.
- [ ] **[docs] plaintext-by-default posture** — flag that all HTTP + MAVLink/RTP surfaces are
      cleartext by default; TAK TLS (`:8089`) is the only wired-in transport encryption.
- [x] **[cleanup] drop `# pragma: no cover` on pure logic** in `fpv/crsf/rc.py` (span==0 guards)
      and source the remaining magic numbers. Verified fixed (2026-07-08 reconciliation): `rc.py`
      has no `# pragma: no cover`, its `pad`/`count` are function parameters (not baked literals),
      and the monitor poll interval is `settings.monitor.poll_interval_s` (config-driven).

## Vineyard SCOUT (initiative Scout — **Implemented (software); hardware validation pending**)
> Structural-anomaly scouting for a vineyard block: a mapping survey (RGB + autopilot pose) →
> georeferenced, deduplicated anomaly map on TAK/ATAK + a thin web triage view. `meshsa.scout`
> subpackage. Precision **A1 vine-level + RTK**; **B1** (no control loop); detection via a
> `Protocol` seam + synthetic replay now, IMX500 later. Peer review:
> [PLAN_PEER_REVIEW_SCOUT.md](PLAN_PEER_REVIEW_SCOUT.md); spec:
> [specs/initiative-scout.md](specs/initiative-scout.md). Gates green (871 tests, 98.7% cov).

- [x] **GATE — CHARTER §3 carve-out:** ratified 2026-07-05 for *offline* survey/waypoint
      **generation + export for a human to load** (no autonomy/auto-upload/BVLOS/MAVLink writes);
      recorded in [CHARTER.md](CHARTER.md) §3.
- [x] **Scout.0** contracts + replay: `GeoDetection`/`Block`/`PixelDetection` schemas (reuse
      `models.Detection` on the wire); seeded boustrophedon replay at known ground truth with
      M8N-vs-RTK noise (`scout/replay.py`).
- [x] **Scout.1** georef + pose/AGL: extended `cv.geo` additively (`Terrain` seam + DEM loader via
      `rasterio` extra, roll, covariance `ground_error`) **and** `PoseFuser` (`ATTITUDE`+position→AGL).
- [x] **Scout.2** fusion: `TimeSync` (max-skew drop-and-count), `Deduplicator` (cluster
      `vine_spacing/2`), `InMemory`/`Sqlite` store; M8N cross-vine-merge regression test kept.
- [x] **Scout.4** ground station: emit `GeoDetection` via `detection_codec`→MARKER→`cot`→ATAK
      (`marker_stale_s` overrides the 120 s CoT default); `aiohttp`+MapLibre view for
      tag/reject/inspect + GeoJSON/CSV export, loopback-default + fail-closed.
- [x] **Scout.3** survey coverage analysis + `export_mission` `.plan`/`.waypoints` (carve-out
      ratified; wired into `meshsa-scout gen-mission`).
- [ ] **Scout.5** `[HW]` companion glue: real MAVLink `PoseSource` fusion + IMX500 `DetectionSource`
      over ArduPilot SITL; on-device, not in CI (contracts + fakes in place).
- [x] **Config/deps:** `ScoutConfig` (`MESHSA_SCOUT_*`) in `NodeConfig.from_env`; `geo`/`scout`
      extras (`rasterio`) + mypy `ignore_missing_imports` in pyproject **and** root `mypy.ini`;
      `meshsa-scout` console script; web = `aiohttp`. DEM file-open + JS pragma/omit pre-declared.
- [ ] **[HW] validation (→ Validated):** camera calibration (H1), RTK (H2), DEM tile (H3),
      IMX500 model (H4), one-block field accuracy pass (H5).

### Scout code-quality backlog (2026-07-05 gap scan — see [GAP_ANALYSIS_SCOUT.md](GAP_ANALYSIS_SCOUT.md))
- [x] **[config]** Wire dead config to behaviour: `dem_path`→`build_terrain`, `store_path`→
      `build_store`, `marker_stale_s`→`make_marker_codec`; add `camera_*` intrinsics fields
      (retire the hardcoded default camera on `replay`/`gen-mission`).
- [x] **[security]** Station operator page hardened against an XSS sink (`textContent`/
      `createElement`, no `innerHTML`).
- [x] **[efficiency]** `TimeSync.align` O(log n) via a sorted index; `coverage_fraction` bands
      transects by `v` (binary search) instead of a full scan.
- [x] **[docs]** Reconcile CHANGELOG (reflect-not-reject) and spec §5/§7/§9 (config table, DEM
      pragma posture, legacy-fallback wording).
- [x] **[test]** Cover health-check failures, station auth-denials + malformed body, gen-mission
      single-output, and the new wiring helpers (scout ~100%, global 99.14%).

## Known risks / watch-items
- FreeTAKServer dependency conflicts on aarch64 (opentelemetry/greenlet/eventlet) — pinned
  for now; re-verify on FTS upgrades.
- arm64 `npm install` for the Configurator source build is untested upstream — prefer the PWA.
- Jetson eMMC is space-constrained; caches/Docker/venvs and `/usr/local/cuda`+`/opt` are
  relocated to the NVMe SSD (see `flightctl/scripts/`).
- **Insecure-by-default building blocks:** mavlink2rest, FreeTAKServer, and the TAK
  transports are all unauthenticated/plaintext out of the box — any commanding or field
  deployment must add the auth/TLS/confirmation layer first.
- **Moving targets:** pin versions for `mavlink2rest`, PyTAK, and Betaflight — all change fast.
- **Unverified (needs focused follow-up research):** MAVLink 2 message signing, multi-GCS
  link arbitration, arm64 signed-image + systemd-hardening specifics, and Meshtastic
  store-and-forward semantics were flagged but not confirmed in the 2026-06 research pass.
