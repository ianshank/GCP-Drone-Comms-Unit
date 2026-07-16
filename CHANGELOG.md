# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **On-board multi-object tracker (`jetson_yolo_gcs`; read-only, advisory).** A new `tracking/`
  seam (`TrackerBase` ABC + `tracker_registry` + `build_tracker`) with a Norfair backend
  (BSD-3-Clause; Kalman-SORT) assigns a stable id to detected objects across frames. It runs in the
  pipeline after detection, **off by default** (`TRACKER_ENABLED=false`), and its output feeds
  **only** the health snapshot (`tracks_active`/`tracks_total`/`dropped_tracks`) — it never
  influences `LANDING_TARGET` target selection (pinned by a regression test) and issues no vehicle
  writes. The stable id rides on a local `TrackedDetection` wrapper; the frozen `Detection` is
  unchanged. A tracker fault is dropped-and-counted (advisory), never fatal. Norfair is an optional
  `[tracker]` extra with a lazy import (package import stays light; `numpy<2` transitive pin noted).
  Behind CHARTER §6 carve-out (ratified 2026-07-16); design in
  [docs/specs/initiative-d-perception.md](docs/specs/initiative-d-perception.md). No wire/schema
  change. Coverage 99.3% (≥96% floor).

### Security
- **Fail-closed `/healthz`+`/metrics` bind (M2).** The observability server was the only aiohttp
  surface that did not route through `netauth.validate_bind` — its host is operator-overridable
  off-loopback (`MESHSA_HEALTH_HOST`), which would expose `/metrics` (router/transport/inference
  counters) unauthenticated. New `HealthConfig.token` (env `MESHSA_HEALTH_TOKEN`) + a pure
  `validate_healthz_bind` guard now **refuse a non-loopback bind without a token**, and `/metrics`
  is bearer-gated when a token is set. The routing/auth lives in a new testable
  `build_healthz_app` factory (exercised end-to-end via `TestClient`), not the pragma-excluded
  socket wiring; the bind is validated in `cli.py` **before** `node.start()` so a misconfig fails
  fast without leaking a started node. **Behavior change:** a deployment that binds `health.host`
  off-loopback with no token now refuses to start (previously fail-open). Default (loopback,
  `token=None`) is unchanged, so existing loopback deployments and `/metrics` scrapes are
  unaffected. See [docs/AUDIT_M2_AUTH.md](docs/AUDIT_M2_AUTH.md).

### Added
- **M2 transport/endpoint-authentication audit** ([docs/AUDIT_M2_AUTH.md](docs/AUDIT_M2_AUTH.md)).
  Evidence-backed enumeration of all 16 network-facing surfaces and their auth/encryption posture —
  the prerequisite the implementation plan (Track 0.2 / E.3) requires before the maintainer can rule
  on the Initiative-C commanding M2 gate. Verdict: per-endpoint HTTP auth now fails closed on all
  four HTTP surfaces, but auth is per-surface (not transport-wide) and transports are
  plaintext-by-default outside opt-in TAK TLS — the gate stays closed pending a CHARTER §6 decision.
- **Inference observability (`meshsa.inference`).** `InferenceService.as_dict()` exposes
  `offline_dropped`, `offline_queue_depth`, `intake_dropped`, and `pending_tasks` counters.
  `/metrics` now exports a matching `meshsa_inference_*` series — counters
  `meshsa_inference_offline_dropped_total`/`meshsa_inference_intake_dropped_total` and gauges
  `meshsa_inference_offline_queue_depth`/`meshsa_inference_pending_tasks` — via
  `render_prometheus(metrics, transports, *, inference=...)` and `health.render_metrics` (both
  json and prometheus formats), emitted only when `node.inference_service` is set. The Grafana
  dashboard (`ops/observability/grafana-meshsa-dashboard.json`) gained an "AI Inference" row (2
  panels), and the metric-name drift-guard test now covers all 12 series (8 router/transport + 4
  inference).
- **Inference task-intake backpressure.** `NemotronConfig.max_pending_tasks` (env
  `MESHSA_INFERENCE_MAX_PENDING_TASKS`, default `0` = unbounded) bounds
  `InferenceService.handle_message` task intake, dropping-and-counting into `_intake_dropped`
  (mirrors the existing offline-queue drop-and-count). Default is a no-op.
- **`jetson_yolo_gcs`: PX4 `MAV_FRAME_LOCAL_NED` `LANDING_TARGET` path.** New `MAVLINK_FRAME`
  config (`body_frd` default | `local_ned`) frame-dispatches `LandingTargetBridge.publish`; the
  `local_ned` path projects the current pose to N/E/D and sends `position_valid=1`. Body-FRD wire
  output is unchanged (pin-guarded byte-identical). Three new self-contained modules (no `meshsa`
  import): `geometry/ned.py` (pure, no-numpy `project_pixel_to_ned`, mirroring the `meshsa.cv.geo`
  flat-ground ray-cast), `mavlink/pose.py` (`VehiclePose`, `PoseSource` protocol,
  `MavlinkPoseSource`), and `mavlink/timesync.py` (`TimeSync` offset tracking).
- **`jetson_yolo_gcs`: TIMESYNC + capture-time `time_usec`.** New `MAVLINK_TIMESYNC_ENABLED`
  (default `false`) and `MAVLINK_CAPTURE_TIME_SOURCE` (`publish` default | `capture`) config
  gates whether `LANDING_TARGET`'s `time_usec` is derived from the vehicle-synced capture time
  instead of publish time. Both default to prior (publish-time) behavior.
- **FTS end-to-end harness (M2).** `packages/meshsa/tests/e2e/test_fts_e2e.py` adds
  hardware-free coverage (CotCodec encode/decode round-trip + CotFramer split-stream
  reassembly) that always runs, plus an opt-in live-FTS roundtrip test gated behind
  `MESHSA_FTS_E2E=1` (marked `e2e`, skipped otherwise). `.github/workflows/fts-e2e.yml` is a
  `workflow_dispatch`-only, self-hosted-Jetson-runner job that brings up FreeTAKServer and runs
  the live test; it does not run in normal CI pending a registered runner.
- **`docs/BRANCHES.md`.** Documents branch disposition: `feat/tls-cot-and-fts-pacing` is fully
  superseded (safe to close, human-gated); PR #11 `feat/fc-msp-telemetry-rc-pilot` carries
  unique MSP-RC/M3.2 work and needs a maintainer decision (not closed).

### Changed
- **Reason-keyed `LANDING_TARGET` suppression accounting.** `LandingTargetBridge` gained
  `_note_suppressed(reason, ...)` + `suppressed_snapshot()`, distinguishing `no_heartbeat` /
  `no_pose` / `unprojectable` suppressions (previously one conflated counter);
  `pipeline.py`'s `snapshot()` gained `landing_target_suppressed_by_reason` alongside the
  existing total. The fail-closed autopilot-heartbeat gate still guards both send paths.
- **`jetson_yolo_gcs` `MAVLINK_TIMESYNC_ENABLED` is load-bearing.** The flag now gates whether
  the capture-time path applies the `TimeSync` offset, rather than being informational only.
- **Coverage gates raised.** `meshsa` `--cov-fail-under` 90 → 97 (actual 99.50%);
  `jetson_yolo_gcs` `--cov-fail-under` 85 → 96 (actual 99.34%); root and jetson `AGENTS.md`
  updated to match.
- **Named protocol constants replace magic literals** in the jetson MAVLink path
  (`_USEC_PER_SEC`, `_MAV_FRAME_LOCAL_NED`, `_LANDING_TARGET_TYPE_LIGHT_BEACON`,
  `_IDENTITY_QUATERNION_WXYZ`).

### Fixed
- **`jetson_yolo_gcs` `LOCAL_NED` path fails safe instead of risking a `ZeroDivisionError`.**
  `LandingTargetBridge.publish` now suppresses (returns `False`, no send) rather than raising
  when there is no `PoseSource`, no fresh pose, an unprojectable ray, or a degenerate
  (zero-dimension) camera frame.
- **Pre-existing order-dependent heartbeat-transition test flake.** A jetson heartbeat-gate
  test asserted on a message that depended on prior test ordering; it now matches the
  gate-open transition message directly.

### Fixed
- **`meshsa.inference` Track-B gap-analysis hardening (post-review).** Scoped the offline replay
  queue to genuine connectivity/transient failures (`InferenceTransportError`, or `429`/`5xx`
  that exhausted retries) via a new `_is_offline_retryable` predicate reusing a shared
  `_is_transient_status` — a permanent `401`/`400`/malformed-payload failure is no longer queued
  (it would replay forever and never drain). Offline replay now runs through the same
  `_gated_analyze` rate-limit gate as live requests (min-interval spacing applied **before** a
  per-call semaphore permit, so a backlog can't burst and a permit isn't spent while merely
  waiting); a permanent replay failure is dropped-and-counted and draining continues (no
  head-of-line block) while a transient one returns to the FIFO front and stops. Removed the
  hardcoded `"summary"` unwrap key (now the configurable `guided_json_summary_field`) and log a
  `structured_parse_fallback` when structured parsing falls back to raw text. `guided_json_schema`
  is now validated as a JSON object at `NemotronConfig` load (fail-fast) and the allow-list guard
  is deduplicated. Addresses Copilot review on PR #26.

### Added
- **`meshsa.inference` Track-B hardening (spec `docs/specs/initiative-e-inference.md` §5).** Four
  additive, default-off options on `NemotronConfig` (all `MESHSA_INFERENCE_*` env-bound, no magic
  numbers): **rate limiting** (`min_interval_s` + `max_concurrent_requests` — a `BoundedSemaphore`
  caps concurrency and a clock-driven min-interval gate caps rate, enforced in `InferenceService`);
  **structured (JSON) parsing** (`response_format` + `guided_json_schema` — a schema is sent as
  NVIDIA `nvext.guided_json`, else the portable `response_format:{"type":"json_object"}` toggle,
  and `_parse` unwraps a JSON `summary` field with a raw-text fallback so the text path never
  regresses); **multi-model** (`models` allow-list + `NemotronConfig.with_model()` with a
  construction-time validator); and **offline fallback** (`offline_queue_max` bounded deque that
  queues failed envelopes drop-and-count on overflow and replays them on the next success). Every
  default is a no-op, so existing deployments are unchanged; `inference.py` stays at 100% coverage.
- **`docs/ROADMAP_RECONCILIATION.md`.** Records that an externally-circulated "Architectural
  Roadmap" (Google Cloud / Langfuse / Spring-Boot-JUnit / autonomous agent-swarm) was written
  without repo access and is largely inapplicable or out of scope per CHARTER §3; maps each claim
  to reality and notes the one in-scope slice that became the inference Track-B work above.
- **`meshsa.scout` — vineyard structural-anomaly scouting (spec `docs/specs/initiative-scout.md`;
  CHARTER §3 offline-survey carve-out ratified 2026-07-05).** Turns a mapping survey (RGB
  detections + autopilot pose) into a georeferenced, deduplicated anomaly map on the existing
  TAK/CoT field map plus an optional thin `aiohttp`+MapLibre operator view. New subpackage with
  `Protocol`/registry/config seams so it builds and tests green with **no hardware** against a
  seeded synthetic replay harness. Modules: `schemas` (`GeoDetection`/`Block`/`PixelDetection`),
  `pose` (`ATTITUDE`+position→AGL fusion), `terrain` (flat + DEM via the optional `geo`/`rasterio`
  extra), `sync` (max-skew drop-and-count), `dedup` (spatial clustering; keeps the M8N cross-vine
  merge regression proof that A1 needs RTK), `store` (in-memory + stdlib SQLite + GeoJSON/CSV),
  `replay`, `survey` + `export_mission` (QGC `.plan` / ArduPilot `.waypoints`, **offline export
  for a human to load — no autonomy, no auto-upload, no MAVLink writes**), `pipeline`, and a
  loopback-default, fail-closed `station`. New `ScoutConfig` (all `MESHSA_SCOUT_*`, no magic
  numbers) composed into `NodeConfig.from_env`; `meshsa-scout` console script
  (`replay`/`gen-mission`/`run-station`/`--health-check`). Detections ride the **existing**
  `DetectionCodec`→MARKER→`cot` path additively (no schema bump). `meshsa.cv.geo` gained
  backwards-compatible extensions — `Terrain` seam, `roll_deg`, terrain-aware range refinement,
  a covariance `ground_error`, and `initial_bearing`/`ground_distance_m` helpers (existing callers
  and tests unaffected); a past-nadir ray now **reflects** (complementary depression, azimuth+180)
  so the full frame projects instead of yielding a negative range.
- **Scout gap-analysis remediation (`docs/GAP_ANALYSIS_SCOUT.md`).** Wired previously-dead
  `ScoutConfig` fields to behaviour: `dem_path` → `build_terrain` (DEM via the `geo` extra, flat
  fallback + warning when rasterio is absent), `store_path` → `build_store` (SQLite vs in-memory),
  `marker_stale_s` → `make_marker_codec` (so scout MARKERs outlive the 120 s CoT default), and new
  `camera_*` intrinsics fields (retiring the hardcoded default camera on the `replay`/`gen-mission`
  paths — Track H1 calibration). Hardened the station operator page against an XSS sink (DOM
  construction via `textContent`, no `innerHTML`). Efficiency: `TimeSync.align` is now O(log n)
  via a lazily-sorted index, and `coverage_fraction` bands transects by `v` (binary search) instead
  of a full scan. De-duplicated the nadir-depression constant and extended coverage to ~100% on the
  scout modules (892 tests, 99.1%).
- **Injectable `HttpTransport` seam for the inference layer (CHARTER §4.3/§4.4).** `meshsa`
  now exports `HttpTransport` (a runtime-checkable `Protocol`), `HttpResponse`, the default
  socket-backed `AiohttpTransport`, and neutral errors `InferenceError` /
  `InferenceTransportError` / `InferenceHttpError`. `NemotronClient`, `InferenceService`, and
  `build_node` accept an optional `transport=` (default unchanged: a reused `aiohttp` session).
  The stateful HTTP I/O (session reuse under an `asyncio.Lock`, error mapping) now lives in the
  transport — the only `# pragma: no cover` glue — while the retry/backoff/429/parse logic stays
  pure and is 100%-covered with a fake. Persistent non-2xx responses now raise
  `InferenceHttpError` (carrying `.status`) and transport/timeout failures raise
  `InferenceTransportError`, instead of leaking `aiohttp`-typed exceptions to callers.
  Backwards-compatible: existing callers that pass no `transport` are unaffected. Debug-level
  structured logs were added around the request/retry path.
- **Inference retry hardening.** Non-429 4xx (e.g. a bad API key → 401) now **fail fast**
  instead of burning the whole retry budget; 429 and 5xx still retry. Backoff is **capped** by
  a new `NemotronConfig.backoff_max_s` field (default 30 s, env `MESHSA_INFERENCE_BACKOFF_MAX_S`)
  to avoid unbounded sleeps. A malformed completion body now raises `InferenceError`
  ("malformed completion payload") rather than a raw `KeyError`/`IndexError`, so callers catch a
  single error hierarchy. `AiohttpTransport` gained an injectable `session_factory` so its
  session-reuse/error-mapping logic is unit-tested (only real `aiohttp.ClientSession`
  construction remains `# pragma: no cover`).
- **Object-detection → CoT marker bridge (Phase A of the DeepStream/YOLO11 work).** A
  detector process (DeepStream/YOLO11, separate process) sends one JSON detection frame per
  tracked object over UDP to the new `detection_ingest` source transport; the new
  `detection` codec maps it to a `MessageKind.MARKER` Envelope, and `CotCodec` gained a real
  **MARKER encode path** (configurable `marker_type`, default `a-u-G` = unknown ground, with
  the class label + confidence in `<contact>`/`<remarks>` and a `_meshsa_det` detail element)
  so detections render as **markers, not friendly PLI tracks**. `meshsa.cv.geo` provides the
  pure pixel→ground projection (geodetic with a GPS/attitude pose, sensor-relative bearing
  otherwise) for the detector to call. New `meshsa.models.Detection`. Config exemplar:
  `flightctl/configs/jetson_gateway.yolo.json` (detection_ingest + tak_tcp). Hardware-free
  and fully tested; the DeepStream device pieces (install, YOLO11 FP16 engine, pyds probe)
  are later phases.

### Fixed
- **Inference test gate no longer couples to an `aiohttp` version.** The suite mocked the HTTP
  boundary with `aioresponses`, which reaches into `aiohttp` internals and broke whenever the
  environment shipped `aiohttp >= 3.10` (`ClientResponse.__init__() missing … 'stream_writer'`).
  The previous band-aid pin (`aiohttp >= 3.9, < 3.10`) was removed; the boundary is now an
  injectable `HttpTransport` `Protocol` (see Added) and tests use a pure in-memory fake, so they
  pass on any supported `aiohttp` (verified on 3.14). `aioresponses` is dropped from `dev`.
- **CI/CD test failures on missing dependencies**: Added dynamic mocking of `sys.modules['anthropic']` in `test_build_agent_resolves_env_vars` to prevent import errors in environments without the `[llm]` extra.
- **Mypy unused-ignore and call-arg warnings**: Dynamically imported `ultralytics` using `importlib.import_module` and cast `cv2.VideoCapture` to `Any` to resolve environment-dependent type check errors.

### Security
- **Commander service no longer receives the whole process environment.**
  `flightctl/run_commander.py` previously passed `dict(os.environ)` into
  `build_service`; it now reads only the one secret it needs (the MAVLink2 signing-key
  path) and passes that explicitly, so no token/key can leak through that seam (e.g.
  into a future audit "config snapshot" record).
- **SA-assistant `/chat` now bounds prompt length** (`MAX_PROMPT_CHARS = 8000`),
  returning 400 instead of forwarding an unbounded prompt to the model — closes a
  cost/latency DoS on the (optionally off-loopback) endpoint.

### Changed
- **Commander config is now schema-validated** (`meshsa.command.CommanderConfig`,
  pydantic). Loading is unchanged for valid files; unknown keys are still ignored and
  types are still coerced. `mavlink_endpoint` and `audit_path` remain **required**
  (previously a bare `KeyError`; now a clear startup message). Out-of-range numerics
  (`ack_timeout_s`, `max_attempts`, `arm_report_max_age_s`, `port`,
  `target_system`/`target_component`) **log a warning this release and will be rejected
  in a future release** — fix flagged values now.
- **Operator-facing numeric parsing reports the offending setting.** Env/CLI/config
  scalars (`meshsa.config.NodeConfig.from_env`, `meshsa.cli`, `meshsa.llm` port) now
  parse via a shared helper that names the field on a bad value instead of raising a
  bare `invalid literal for int()`. `MESHSA_LLM_PORT` is additionally range-checked to
  `1..65535`.
- **Unified `MonotonicClock` in FPV**: Deduplicated FPV monotonic clock implementation by using the framework-level `MonotonicClock` from `meshsa.protocols`.
- **Configurable LLM prompt length and agent parameters**: Added environment variable bindings `MESHSA_LLM_MAX_PROMPT_CHARS`, `MESHSA_LLM_MAX_TOKENS`, and `MESHSA_LLM_MAX_ITERATIONS` to the LLM assistant server and agent.
- **Environment variable loading for Commander**: Added `from_env()` method to `CommanderConfig` supporting `MESHSA_COMMANDER_CONFIG_JSON` blobs and individual scalar overrides.
- **Injectable clock in `FlightLogger`**: Replaced direct `time.monotonic()` calls inside the flight logger writer thread with the injected `self._clock.now()` to allow deterministic testing via `FakeClock`.

### Migration (already-merged commanding changes worth calling out)
- **`NemotronClient.analyze` no longer raises `aiohttp`-typed exceptions.** A caller that
  previously caught `aiohttp.ClientError`/`ClientResponseError` (or `KeyError`/`IndexError` on a
  malformed body) should now catch the `meshsa.InferenceError` hierarchy
  (`InferenceTransportError` for network/timeout, `InferenceHttpError(.status)` for HTTP errors,
  `InferenceError` for a malformed payload). Nothing in-repo caught the old types, so this is
  internal-only; external callers should migrate their `except` clauses.
- `MavlinkCommandLink.start()` is **required** before `send()`/`recv_ack()` (signing is
  configured in `start()`; sending first would transmit unsigned frames). The
  production path (`MavlinkCommandPump.start()` → `link.start()`) already does this.
- The commander audit JSONL record shape is pinned as `command.AUDIT_RECORD_FIELDS`
  = `("t", "event", "data")`; treat changes to it as a wire-format break.
- **SA-assistant server no longer exposes an unauthenticated surface by default.**
  `meshsa.llm` bound `0.0.0.0` with no auth, so `/chat` — which discloses live
  drone/track positions and spends Anthropic tokens — was reachable off-host. It now
  binds `127.0.0.1` by default (`DEFAULT_HOST`), accepts a `MESHSA_LLM_TOKEN` bearer
  token enforced on `/chat` via constant-time compare, and **fails closed**:
  `validate_bind` refuses to start on a non-loopback host when no token is set. Restores
  the M2 "no unauthenticated surface by default" invariant (was the gate on the
  ratified commanding initiative).

### Added
- **Prometheus/JSON metrics export.** `RouterMetrics.as_dict()` plus a hand-rolled
  `meshsa.render_prometheus(metrics, transports)` (no new dependency) emit
  `meshsa_rx_total`/`meshsa_tx_total`/`meshsa_forwarded_total`/
  `meshsa_dropped_undecodable_total`/`meshsa_schema_mismatch_total` and per-transport
  `meshsa_transport_{dropped_inbox_full,reconnects,rx_frames}{transport="..."}` series.
  An opt-in `/metrics` route on the health listener serves either format, gated by new
  `HealthConfig` fields (`metrics_enabled`/`metrics_path`/`metrics_format`).
- **Per-transport rx observability on polling sources.** `PollingSourceTransport` now
  tracks an `rx_frames` counter and emits a throttled `"source rx"` link-health log line
  (`link="up"`/`"down"`) every `log_every_n` frames or once per `log_interval_s` idle
  window (both configurable constructor params; defaults `100`/`30.0`). `rx_frames` is
  surfaced in the health snapshot.
- **`flightctl/constraints/fts-constraints.txt`.** The FreeTAKServer dependency pins
  (setuptools/opentelemetry/etc.) verified to boot FTS on the Jetson now live in one
  auditable constraints file; `scripts/setup_fts.sh` installs via `uv pip --constraint`.
- **Richer PLI tracks (M3.1): optional course/speed/battery/attitude.** `Position`
  gained optional `course_deg` (validated `[0, 360)`) and `speed_ms` (validated `>= 0`)
  fields, and new `Attitude` and `Telemetry` models carry optional
  roll/pitch/yaw and battery voltage/percent/current. `PliPayload` gained an
  optional `telemetry` block. All fields are optional with `None` defaults and are
  emitted via `model_dump(exclude_none=True)`, so absent keys never reach the wire
  and old readers see byte-identical payloads — **no `SCHEMA_VERSION` bump**.
- **Detail-aware CoT codec.** `CotCodec` now encodes the richer track data as
  guarded `<track>`, `<status>`, `<_meshsa>` (voltage/current) and `<attitude>`
  detail children when present, and decodes them back losslessly while ignoring
  unknown `<detail>` children. The element/attribute names are constructor
  parameters (`track_element`/`status_element`/`attitude_element`/`battery_attr`/
  `vendor_element`) and the whole additive block can be disabled with
  `emit_detail=False`. The `telemetry` codec carries the same optional fields.

### Added (inference)
- **NVIDIA Nemotron inference service (`meshsa.inference`).** An optional, async
  inference bridge that subscribes to mesh traffic, sends messages to the NVIDIA
  Nemotron NIM API for AI analysis, and broadcasts `[AI Insight]` summaries back to
  the mesh. Lazy-imports `aiohttp` so the base install is unaffected; install with
  `pip install meshsa[inference]`. Key features: retry with exponential backoff,
  `aiohttp.ClientSession` reuse, feedback-loop prevention (messages prefixed with
  `[AI Insight]` are never re-analyzed), lifecycle guards (`_running`/`_subscribed`),
  and configurable via 9 `MESHSA_INFERENCE_*` environment variables.
- **Inference env-var bindings in `NodeConfig.from_env()`.** All `NemotronConfig`
  fields (ENABLED, API_KEY, BASE_URL, MODEL, SYSTEM_PROMPT, TEMPERATURE,
  MAX_TOKENS, TIMEOUT_S, MAX_RETRIES) are now settable via `MESHSA_INFERENCE_*`
  environment variables, matching the same precedence pattern as mesh config.
- **`inference` optional extra** in `pyproject.toml` (`aiohttp>=3.8`).
- **`aioresponses>=0.7`** added to the `dev` extras for inference test mocking.

### Fixed
- **`TakMulticastTransport` recovers from receive errors instead of dying.** A transient
  `recv()` error permanently stopped multicast CoT ingestion (the recv loop had no
  `try/except`, unlike the TCP supervisor). The loop now closes the wedged socket,
  rebuilds it via the injected `io_factory`, and backs off via the shared `Backoff`
  (new `backoff_*`/`sleep` constructor params), tracking rebuilds in a `reconnects`
  counter.
- **Prometheus transport label values are now escaped.** `render_prometheus` escaped
  nothing, so a user-configured transport name (`TransportConfig.name`) containing a
  `"`, `\` or newline produced malformed text-exposition output. Names are now escaped
  per spec (`\` → `\\`, `"` → `\"`, newline → `\n`) before embedding in the
  `{transport="..."}` label, keeping each series on one valid line.
- **`PollingSourceTransport` rejects an invalid log-throttle config.** `log_every_n <= 0`
  made the reader thread raise `ZeroDivisionError` on `rx_frames % log_every_n`, and a
  non-positive `log_interval_s` made the idle window meaningless. The constructor now
  validates `log_every_n >= 1` and `log_interval_s > 0`, raising `ValueError` early.
- **`PollingSourceTransport` reader no longer drops iteration errors or mislabels
  shutdown.** The frame iteration after `_poll()` ran outside the `try`, so an error while
  iterating escaped and silently killed the reader thread; it is now inside the guarded
  block. A poll error after the stop event is set now logs at `DEBUG` (a normal stop)
  instead of `WARNING` (which looked like a failure).
- **`serve_healthz` honors `health.metrics_*` config.** The metrics args defaulted to
  hard-coded literals, so `health.metrics_enabled=true` in config did nothing unless the
  caller also passed the flag. The args now default from `node.config.health.*` when left
  unset, so config alone exposes `/metrics`.
- **FPV capture loop no longer busy-loops or dies silently (`meshsa.fpv.camera`).** When the
  source disconnects, `read_frame()` returns `None` immediately; the capture loop now backs off a
  bounded `CameraSettings.idle_poll_s` (new tunable, default `0.1`) instead of spinning at 100%
  CPU, and the whole loop body is wrapped so a transient `read_frame`/`record_frame` failure is
  logged and skipped rather than killing the daemon capture thread.
- **`CaptureWriter.close()` closes the source before joining the capture thread.** A backend
  blocked inside `read_frame()` is now unblocked first, so the bounded join can complete instead
  of timing out against a wedged read.
- **`FlightLogger` no longer persists a live reference to the caller's `video_meta`.** The dict is
  deep-copied on ingest, so a caller mutating it (including nested values) after `start()` can no
  longer silently alter the written `manifest.json`.
- **`FlightLogger` counter updates are thread-safe.** A `threading.Lock` now guards the
  read-modify-write updates to `dropped_records`, `_tel_counts`, `_tel_t_first`/`_tel_t_last`, and
  `_notes` shared across the capture thread, the writer thread, and caller threads, so concurrent
  increments can no longer be lost. The lock is never held across blocking I/O.
- **CoT decode enforces the model bounds on peer values.** `CotCodec.decode` now
  validates the assembled position/telemetry through the `Position`/`Telemetry` models
  (reusing their validators), so numeric-but-out-of-contract CoT attributes (course
  `[0,360)`, speed `>=0`, `battery_pct [0,100]`, `battery_v >=0`) are rejected as
  `MeshSAError` rather than producing an out-of-contract envelope.
- **Telemetry codec `encode` wraps validation errors.** `encode()` validates the
  optional telemetry block too; a pydantic `ValidationError` is now surfaced as
  `MeshSAError` (matching `decode`), so the codec never leaks a raw pydantic exception.
- **CoT decoder hardens richer-detail parsing against malformed peers.**
  `CotCodec._decode_richer_detail` now wraps every `float`/`int` parse of
  `<track>`/`<status>`/`<_meshsa>`/`<attitude>` attributes in
  `try/except (TypeError, ValueError)` and raises `MeshSAError` (logging the
  malformed input at debug). A peer sending e.g. `course="invalid"` no longer
  escapes as a raw `ValueError`.
- **`Telemetry` model now validates battery bounds.** `battery_v` must be `>= 0`
  and `battery_pct` must be in `[0, 100]` when present, mirroring the `Position`
  validators; out-of-range values raise `ValidationError`.
- **Telemetry codec catches pydantic `ValidationError` on decode.**
  `TelemetryCodec.decode` now imports and catches `pydantic.ValidationError`
  alongside `TypeError`/`ValueError`, so a frame with an out-of-range
  `battery_pct`/`course_deg` surfaces as the codec's `MeshSAError` instead of
  leaking a raw `ValidationError`.
- **`flightctl/run_gateway.py` no longer crashes on Windows.** Its
  `loop.add_signal_handler` calls are now wrapped in `contextlib.suppress(NotImplementedError)`,
  matching `meshsa.cli.run`, so the gateway degrades gracefully where signal handlers are
  unsupported instead of raising at startup.
- **`message_from_record` rejects malformed dataset records.** Rebuilding a telemetry
  message from a logged `{type, data}` record with missing/extra fields (log corruption or a
  forward dataset that reshaped an existing record) now raises `TelemetryParseError` instead of
  a bare `TypeError`, so replay fails loudly and consistently with the unknown-type path.
- **`fpv-telemetry-monitor` survives a malformed known frame.** `pump_once` now catches
  `TelemetryParseError` around the parse, logs it, and drops the frame, so a single CRC-valid
  but payload-malformed frame no longer tears down the live monitor loop — matching the
  per-frame drop-and-continue behaviour of `crsf_source`.

### Changed
- **Shared `Backoff` reconnect helper (`meshsa.transports.backoff`).** The exponential
  `initial → min(current*factor, max)` reconnect schedule (with its injectable `sleep`) was
  duplicated in `TakTcpTransport` and `MeshtasticTransport`; it now lives in one place. Public
  constructor options (`backoff_initial_s`/`backoff_max_s`/`backoff_factor`/`sleep`) and the
  observable `reconnects` counter are unchanged; the backoff sequence is identical.
- **`FlightLogger` stream set is single-sourced.** The session JSONL filenames and the
  manifest `files` map now derive from the one `_HEADERS` declaration instead of three
  repeated stream lists; adding a stream is a one-line change. Output is byte-identical.
- **Shared `meshsa.cli.configure_logging(level)` helper.** The duplicated
  `structlog.configure(make_filtering_bound_logger(...))` wiring across the five console
  entry points (`meshsa-base`, `fpv-log-convert`, `fpv-telemetry-monitor`, `fpv-log-replay`,
  the flightctl gateway) now lives in one place.
- **`mavlink_source`: GPS wire scales are now configurable** (`coord_scale`/`alt_scale`
  constructor options), matching the existing `msp_source` pattern, instead of inline
  `1e7`/`1000.0` literals. Defaults preserve `GLOBAL_POSITION_INT` units (degE7, mm), so
  behavior is unchanged; no wire `SCHEMA_VERSION` change.
- **Link-health WARN→CRITICAL staleness multiplier is now configurable** via
  `HealthSettings.health_linkstats_critical_factor` (default `2.0`), replacing the
  hard-coded `2×` in `LinkHealthMonitor`. Default behavior unchanged.

### Removed
- **`HealthSettings.health_fc_telemetry_stale_s`** — an orphan threshold that no §4.2
  link-health rule consumed (no reason code, never read). Removing it keeps config and the
  Phase-1 spec consistent; pydantic ignores the key in older configs (backward-compatible).
  FC-telemetry-staleness monitoring, if desired, needs a defined §4.2 rule + reason code first.

### Added
- **FPV camera capture core (`meshsa.fpv.camera`, Phase 2).** `CaptureWriter` owns one
  daemon `fpv-capture` thread that reads `Frame`s from an injected `CameraSource` protocol,
  stamps each on the **same** `Clock` the flight logger uses (so frame timestamps interleave
  with telemetry on one timebase), records the frame index via the already-shipped
  `FlightLogger.record_frame`, and hands the buffer to an injected `encode` callable over a
  bounded queue that drops-and-counts on overflow (`dropped_frames`). The real OpenCV backend
  is imported lazily behind a `# pragma: no cover` factory, so `import meshsa.fpv` stays
  backend-free. No numpy in our code — frame pixels live in `Frame.data: Any`.
  - New `camera` optional extra (`opencv-python-headless`); Jetson deployments may swap the
    backend for v4l2/GStreamer behind the `CameraSource` Protocol with no code change.
  - `CameraSettings` (fps/width/height/encoder/device/output_basename/capture_queue_len)
    composed onto `FpvSettings`; all knobs are config, no magic numbers.
  - The `frames.jsonl` stream (already wired in Phase 1) now carries real records, and the
    manifest `video` entry is populated (was always `None`) when a `video_meta` dict is
    passed to `FlightLogger`. **`DATASET_SCHEMA` is unchanged (stays 2)** — the camera writes
    the existing `{t, frame_idx}` record and the only manifest change is `video` going from
    `None` to a dict, both additive.
- **Read-only LLM situational-awareness assistant (`meshsa.llm`, opt-in `[llm]` extra).**
  - A natural-language assistant over live drone telemetry and TAK tracks. Strictly
    advisory: every tool is read-only, so it can observe and summarize but never command
    the vehicle or alter the SA picture.
  - `sources` — `DroneState`/`Track` models, `TelemetrySource`/`TrackSource` protocols,
    in-memory `Static*` sources (tests/sim), and lazy-import HTTP sources
    (`Mavlink2RestSource` reads mavlink2rest `:8088`; `FtsTrackSource` reads FreeTAKServer).
    Wire parsing (`parse_global_position_int`, `parse_fts_tracks`) is pure and unit-tested.
  - `tools` — read-only `get_drone_state` / `list_tracks` tool specs + `ToolDispatcher`
    over the source protocols; pure formatters.
  - `agent` — `SAAgent`, a manual Anthropic tool-use loop (Claude Opus, adaptive thinking)
    with the Messages API injected behind a `Protocol` so the loop is fully testable with a
    scripted fake client (no network, no key). `build_agent` lazy-imports `anthropic`.
  - `server` — tiny aiohttp chat endpoint (`POST /chat`) + a self-contained chat widget for
    embedding in a Cockpit iframe; the `meshsa-llm` console script serves it. Request
    handling (`chat_reply`) is framework-free and unit-tested.
  - Ops: `flightctl/llm/` runbook + `llm.env.example`. Model defaults to `claude-opus-4-8`,
    overridable via `MESHSA_LLM_MODEL`. 33 new tests; suite stays at 100% line+branch.

## [0.3.0] - 2026-06-13

### Added
- **`meshsa.fpv` — ground-side FPV telemetry subsystem (Phase 0 Errata E1 + Phase 1).**
  A self-contained subpackage under `packages/meshsa/src/meshsa/fpv/` that ingests CRSF
  telemetry from an ELRS handset module, evaluates link health, logs synchronized
  sessions, and enforces a pre-flight arm gate. Reuses the existing DI/Protocol, pydantic
  config, structlog, and versioning conventions; **no `meshsa` wire `SCHEMA_VERSION`
  change** (the dataset has its own `DATASET_SCHEMA`).
  - `crsf/frame.py` + `crsf/telemetry.py`: CRC8/DVB-S2 framing, address-gated stream
    resync, pure **big-endian** parsers (`LinkStatistics`/`BatterySensor`/`Attitude`/
    `FlightMode`); unknown types count, malformed known types raise.
  - `crsf/link.py`: poll-driven `CrsfLink` (no own thread) with self-echo suppression
    (Errata E1.2 — exact-byte primary + self-addr-RC secondary, `echoes_suppressed`
    counter) and an `AddressProber` with the `probe_margin` gate (E1.3). Injectable
    `CrsfSerial` seam; the pyserial default factory is lazily imported and
    `# pragma: no cover`.
  - `telemetry_store.py` + `link_health.py`: bounded per-type history; co-signal health
    model (stale LinkStats can never be OK; downlink-degrading early warning; version-keyed
    sensitivity floors) with immediate degradation / hysteresis-damped recovery.
  - `flight_logger.py`: single writer thread; `rc`/`telemetry` drop-and-count, durable
    block-then-raise `record_event`; per-file `schema_version` headers; `manifest.json`
    with git SHA, `capture_latency_ms`, wiring, drop counters, telemetry rates.
  - `arm_guard.py`: `RCLink` decorator enforcing health-gated **pre-flight** arming with a
    latch that never disarms in flight (see the CHARTER §3 carve-out).
  - Tools / console scripts: `fpv-telemetry-monitor`, `fpv-log-replay`,
    `fpv-log-convert` (JSONL → Parquet, schema-aware).
  - New optional extra `fpv = ["pyserial>=3.5", "pyarrow>=15"]`; nightly installs it for
    real-type mypy + the Parquet path. The subsystem imports cleanly without the extra.
  - Dataset versioning: `fpv/version.py` `DATASET_SCHEMA` with its own compat window
    (ships at `2` in this release — see Changed); `fpv/dataset.py` enforces it on
    replay/convert and tolerates a torn final JSONL line.
  - Specs committed for traceability: `docs/specs/PHASE0_ERRATA.md`,
    `docs/specs/PHASE1_SPEC_v1_1.md`.
  - Tests: 117 new fpv tests; `meshsa.fpv` at 100% line+branch coverage (parsers, health,
    ArmGuard included); full suite 282 passed; mypy `--strict` + ruff clean.
- **`crsf_source` transport — an FPV aircraft as an ATAK air track.**
  `@transport_registry.register("crsf_source")` (`meshsa.transports.CrsfSourceTransport`):
  a receive-only transport that polls a half-duplex `CrsfLink` on a reader thread, decodes
  the CRSF **GPS (0x02)** frame, and emits one position frame per fix through the existing
  `telemetry` codec — so a drone/FPV aircraft reaches ATAK as an **air** track with **no
  router/codec/`SCHEMA_VERSION` change**, the same additive seam as `mavlink_source` /
  `msp_source`. Injectable `CrsfLink` (the pyserial hardware factory is `# pragma: no cover`)
  and configurable GPS unit scaling (`ParserSettings.gps_*`); fully unit-tested with a fake
  `CrsfSerial`, no radio. Closes the deferred air-track seam noted in `docs/ARCHITECTURE.md`.
- **CRSF GPS decode in the telemetry parser.** `crsf/telemetry.py` now parses the GPS frame
  into a new `GpsSensor` message (big-endian lat/lon degrees*1e7, ground speed km/h*10,
  heading deg*100, altitude m with the +1000 m offset, satellite count); GPS is no longer in
  the parsed-and-ignored set. Scales are `ParserSettings.gps_*` fields — no magic numbers.

### Changed
- **CHARTER §3 carve-out (deliberate amendment — ratified by the maintainer 2026-06-12).**
  Adds a bounded exception to the "read-only / not a ground control station" non-goal:
  `ArmGuard` may transmit RC frames **only** for a pre-flight arm interlock; no in-flight
  intervention.
- **Dataset schema `DATASET_SCHEMA` 1 → 2 (`fpv/version.py`).** `GpsSensor` is a new
  persisted `telemetry.jsonl` record type that an older build cannot reconstruct, so a v2
  dataset is forward-incompatible for v1 readers. `MIN_COMPATIBLE_DATASET` stays `1`: this
  build still reads v1 sessions (with a `DatasetCompatibilityWarning`), and an older build
  correctly rejects a v2 dataset rather than failing mid-replay. The meshsa **wire**
  `SCHEMA_VERSION` is unchanged — `crsf_source` rides the existing `telemetry` codec.
- **Shared `PollingSourceTransport` base for the flight-source transports
  (`transports/polling_source.py`).** `crsf_source`, `msp_source` and `mavlink_source` were
  near-identical (reader-thread lifecycle, shutdown, position-frame builder); that plumbing now
  lives in one base, with each transport supplying only its link I/O (`_poll`/`_on_open`/
  `_close`). Removes the triplicated code and makes the shutdown/robustness behavior below
  shared. Public registry names and APIs are unchanged.

### Fixed
- **`crsf_source`: a single malformed frame no longer kills the reader thread.** A CRC-valid
  CRSF frame can still fail payload-level parsing (`TelemetryParseError`); per-frame parse
  errors are now caught, logged, and dropped so telemetry keeps flowing. Reader shutdown is
  also immediate (a `threading.Event` replaces the `time.sleep` poll wait), and `link.close()`
  is guarded so a raising close can't break `stop()` — matching `msp_source`/`mavlink_source`.
- **`meshtastic_radio`: resolve pypubsub lazily in `start()`, not `__init__`.** Constructing
  a `MeshtasticTransport` (e.g. for config validation in `build_node`) no longer imports the
  optional `pypubsub` dependency, matching the lazy-optional-dep pattern used by
  `health`/`msp_source`/`mavlink_source`. Fixes `test_build_node_forwards_mesh_config_to_meshtastic`
  under the `[dev]`-only CI install.

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
