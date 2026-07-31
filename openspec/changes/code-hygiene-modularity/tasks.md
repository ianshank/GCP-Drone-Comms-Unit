# Tasks — code-hygiene-modularity

> Order binding. Each task: implement → tests green → ruff/mypy clean → coverage gate →
> `bind_guard` clean → commit. Checkboxes reflect landed commits on
> `claude/code-hygiene-modularity-xrapgv`; this file is updated in the same commit as the
> work it tracks. Explicit stop points for review after T-2, T-4, T-6, T-7, T-8.

## Phase 0 — Spec + preconditions
- [x] T-0.1 This bundle (`proposal.md`, `design.md`, `tasks.md`, three spec deltas),
      `docs/specs/meshsa-core.md`, `docs/OPENSPEC_CODE_HYGIENE_PEER_REVIEW.md`, registered in
      `docs/specs/README.md`.
- [ ] T-0.2 CHARTER §3 amendment text drafted and reviewed (design D-2's wording); the actual
      `CHARTER.md` edit lands in T-7.3 alongside the dependency it describes, not before —
      consistent with every existing carve-out being dated to when the capability lands.

## Phase 1 — Verified bug fixes
- [x] T-1.1 `Cache-Control: no-store` on `ui/app.py`'s `/api/*` JSON routes; salvage the S5a
      assertion from `deliverables/meshsa-ui-validation/tests/test_ui_validation_scenarios.py`
      into `packages/meshsa/tests/`.
- [ ] T-1.2 `meshsa/_webpage.py` (SRI-pinned MapLibre tags + `_js_literal`, sourced from
      `ui/_html.py`); `scout/station/_html.py` adopts (fixes the floating `maplibre-gl@4` CDN
      reference with no integrity attribute, and the bare `json.dumps(token)` injection with
      no `</script>` escaping).
- [ ] T-1.3 `compact.py`'s `_make_compact` registry factory passes `**kwargs` through instead
      of discarding them (`CompactCodec.__init__` already accepts `supported_schemas` — only
      the factory dropped it); registry-path test.
- [ ] T-1.4 `meshsa/defaults.py` + port table; `HealthConfig.port` 8088→8098; `cli.py`
      `--healthz-port` default; `ops/observability/README.md` (4 references);
      `docs/AUDIT_M2_AUTH.md` port row; `CHANGELOG.md` breaking-default entry.
- [ ] T-1.5 `scout/cli.py` resolves `ScoutConfig` from environment so the 22 wired
      `MESHSA_SCOUT_*` variables (including `MESHSA_SCOUT_STATION_TOKEN`) take effect;
      `CHANGELOG.md` entry marked operator-visible (an operator with
      `MESHSA_SCOUT_STORE_PATH` already exported moves from the volatile in-memory store to a
      file-backed one on upgrade).
- [ ] T-1.6 `llm/sources.py`'s two blanket `except Exception` handlers gain structlog
      warnings before their degraded returns, narrowed to
      `aiohttp.ClientError | asyncio.TimeoutError | ValueError`.

## Phase 2 — Gate widening
- [ ] T-2.1 Pre-commit ruff/format run repo-wide; mypy hooks call each package's real config;
      fix the fallout in the same commit; CI lint scope adds `tools/`.
- [ ] T-2.2 `scripts/validate-pre-pr.sh` gains real Python steps (both packages' pytest +
      mypy, `bind_guard`, governance hook tests).
- [ ] T-2.3 `git mv artifacts/mockup-sandbox lib/api-client-react archive/`; fix the two
      invalid `COPY` lines in the root `Dockerfile`; update `tsconfig.json`/
      `pnpm-workspace.yaml`; delete `scripts/src/hello.ts`, `scripts/post-merge.sh`, the dead
      `Makefile` `db-migrate`/`db-studio` targets; new CI `ts` job
      (`pnpm install --frozen-lockfile && pnpm -r run typecheck && pnpm -r run lint && pnpm -r run test`).
- [ ] T-2.4 `bind_guard.SCAN_GLOBS` widened to include `flightctl/**/*.py` and
      `tools/**/*.py`, excluding `tools/**/tests/**` and `bind_guard.py` itself
      (design D-9); pre-scan documented before fixes; flip the salvaged
      `test_mavlink_bind_guard.py` strict-xfail now that the guard it expects has shipped.
- [ ] T-2.5 Ruff config consolidated to root `ruff.toml` (path-scoped per-file-ignores);
      `mypy.ini` gains jetson's stub-ignore overrides; verify `ruff check` output is
      byte-identical before/after.

## Phase 3 — Shared foundations
- [ ] T-3.1 `meshsa/_web.py` (design D-5); migrate all four app factories; salvage the
      remaining deliverables scenarios (S4d, S5, S6); collapse `scout/station/app.py`'s
      byte-identical `/detections` + `/export.geojson` handlers.
- [ ] T-3.2 `meshsa/_envconfig.py` (design D-11); migrate `NodeConfig`, `fpv/config.py`,
      `llm/server.resolve_config`, `cli.py`'s env helpers.
- [ ] T-3.3 `meshsa/_frame_codec.py` + `SchemaGated` mixin; `telemetry.py`/`detection_codec.py`
      adopt; extract an envelope-builder from `DetectionCodec` so `scout/pipeline.py` stops
      JSON-round-tripping detections through the codec.
- [ ] T-3.4 `meshsa/_geojson.py` (finite-value guard); `scout/store.to_geojson` and
      `ui/snapshot.py` adopt.
- [ ] T-3.5 `meshsa/_queues.py` (`BoundedDropQueue`); adopt in `flight_logger.py`,
      `fpv/camera.py` (fixes its unguarded cross-thread counter); `defaults.py` sweep across
      the queue-maxsize, backoff, and endpoint-literal call sites.
- [ ] T-3.6 Geodesy consolidation into `cv/geo.py`: `scout/survey.py`'s `_LocalFrame` gains the
      pole guard `cv/geo.py` already has; `scout/replay.py`'s hand-rolled inverse projector
      moves beside the forward one with a round-trip property test.
- [ ] T-3.7 `meshsa/mavlink_constants.py` + a shared units-scaling helper for
      `llm/sources.py`/`transports/mavlink_source.py`.
- [ ] T-3.8 `scout/schemas.py` shares lat/lon/confidence validators with `models.py`; statuses
      become a `StrEnum`; `with_status` uses `model_copy`; a typed
      `GeoDetection.to_detection_frame()` replaces the stringly-typed mapping in
      `pipeline._to_envelope`.

## Phase 4 — Class splits (facades preserve public constructors)
- [ ] T-4.1 `InferenceService` → `_RateGate` + `_OfflineQueue`; mechanical split of
      `tests/test_inference.py`.
- [ ] T-4.2 `transports/tak.py` → `TlsSettings` + `build_context()`;
      `TakMulticastTransport` moves to `transports/tak_multicast.py` with a matching
      `.claude/governance.yaml` bind-guard exception entry and `docs/AUDIT_M2_AUTH.md` path
      update in the same commit.
- [ ] T-4.3 `fpv/flight_logger.py` → `_SessionPaths`, `_ParquetSink`, `GitHeadProvider`
      protocol (moves the `subprocess` call out of the logger class); stale "Phase 1/2 stub"
      comments removed.
- [ ] T-4.4 `cot.py`'s `CotCodec` → `_CotNaming` + module-level encode/decode functions behind
      the unchanged facade.
- [ ] T-4.5 jetson `LandingTargetBridge` → `_SuppressionCounter` + frame-encoder strategies;
      `Pipeline` → `PipelineMetrics` + `_PublishPolicy`; `idle_poll_s` sourced from
      `PipelineSettings.model_fields` instead of a re-hardcoded literal.

## Phase 5 — `fpv/` prune and decouple
- [ ] T-5.1a Safe deletions (design D-1): `AddressProber`/`ProbeResult`/`ProberSettings`,
      `fpv/camera.py` + `CameraSource` + unused `CameraSettings` fields,
      `TelemetryStore.age_s`/`.history`, `SUPPORTED_DATASET_SCHEMAS`, `crsf/__init__.py`
      re-exports, `llm/server.py`'s `MAX_PROMPT_CHARS` alias. `CHANGELOG.md` entry.
- [ ] T-5.1b Ratified-carve-out surface kept and marked (design D-1): module notes on
      `arm_guard.py`, `crsf/rc.py`, `send_rc`, `RCLink`, `record_rc`; `NEXTSTEPS.md` decision
      item for a maintainer (wire an entry point, or amend the charter to retire it).
- [ ] T-5.2 `HealthReport`/`HealthState` move to a neutral module; `meshsa/_logging.py` leaf;
      cycle-guard test (design D-9 — no transports registration change).
- [ ] T-5.3 One `is_fresh(t_last, now, max_age_s)` predicate replacing the three-way
      freshness-gate duplication (`fpv/arm_guard.py`, `command/safety.py`,
      `command/health.py`'s bare `3.0` literal); single configured window.
- [ ] T-5.4 `fpv/tools/_common.py` (shared arg-parse/run scaffold); `replay.py` threads
      `store_history_len` from config instead of a hardcoded `512`; `CRSF_MAX_FRAME_LEN`
      single-sourced; `convert.py`'s `_STREAMS` derived from `flight_logger._HEADERS`;
      `SettableClock` promoted to `meshsa/protocols.py`; `MonitorSettings` moves into
      `tools/`; `JsonlStream` writer shared between the flight logger's events stream and
      `command/audit.py`.

## Phase 6 — `scout`/`llm` correctness
- [ ] T-6.1 `scout/store.py`: connection-per-operation under `contextlib.closing` run in an
      executor (off the aiohttp event loop); `set_status` becomes a single atomic `UPDATE`;
      `add_many` batch transaction; DDL/INSERT column lists derived from `_FIELDS`;
      `user_version` pragma check on open.
- [ ] T-6.2 `scout/pipeline.py`: `TimeSync` built once for the pipeline's lifetime instead of
      rebuilt (and its alignment buffer discarded) on every `ingest()` call; `ingest_stream`
      wires the documented-but-dead `PoseSource`/`DetectionSource` seam as the real entry
      point; `_project_one` extracted from the 65-line `ingest` body.
- [ ] T-6.3 `scout/terrain.py`: an explicit `dem_path` that fails to load now fails closed
      instead of silently downgrading to flat-earth; out-of-grid queries drop into a distinct,
      counted bucket instead of clamping to the edge value silently; an assertion guards the
      axis-aligned-raster assumption; the numpy fast path gains test coverage.
- [ ] T-6.4 `scout` miscellany: a coarse grid index replaces `dedup.py`'s quadratic scan and
      surfaces per-cluster observation counts; `scout/replay.py` renames to `scout/synth.py`
      (it collides in name only with `fpv/tools/replay.py`) and its `__post_init__` simulation
      becomes an explicit `build_flight()` factory; `survey.coverage_fraction` uses integer
      sample ranges; `cli.py`'s `_HEALTH_BUDGET_M` derives from `ground_error(...)`; mission
      file writes become atomic; the station server accepts a real store path; `--health-check`
      becomes a subcommand; `export_mission.py`'s home-defaulting and plan-field magic numbers
      become a helper + named constants.
- [ ] T-6.5 `llm/agent.py`: a `ModelProfile` bundling model/thinking/effort with pairing
      validation; explicit `stop_reason` branches (a refusal or `max_tokens` truncation no
      longer renders as an empty chat bubble); the agent's env-only knobs move into
      `ServerConfig`; `build_agent` becomes pure wiring.
- [ ] T-6.6 `llm` miscellany: a single `_TOOLS` mapping replaces the triplicated tool
      registry (spec list / dispatch if-chain / dead `names`); a shared `_get_json` helper
      with a lifecycle-managed session replaces two independently-reimplemented,
      fresh-session-per-call HTTP fetches; `DroneState` reuses the shared lat/lon validators;
      the chat widget moves to an `importlib.resources` HTML asset with a path-safe fetch;
      `build_app(agent, cfg: ServerConfig)` replaces loose positional args.

## Phase 7 — `meshsa-core` extraction
- [ ] T-7.1 Create `packages/meshsa_core/` (design D-2); move the corresponding tests; add
      the anti-cycle test; wire installs — both CI jobs, `nightly.yml`, `fts-e2e.yml`,
      `tools/Makefile`, the session-start hook, `release.yml` (build order), `tools/Dockerfile`,
      `mypy.ini`'s `mypy_path`, `AGENTS.md`/`CONTRIBUTING.md` command tables.
- [ ] T-7.2 meshsa adopts the re-export shims (design D-3); `netauth.py` becomes the
      no-`def`-of-its-own shim (design D-4); `.claude/governance.yaml`'s `canonical_module`
      flips to `meshsa_core.netauth` in this same commit; governance hook tests updated;
      `docs/AUDIT_M2_AUTH.md` references updated. Verification runs `bind_guard.py` and the
      link-loss soak suite explicitly.
- [ ] T-7.3 jetson adopts the re-export shims; bridge's `_default_connection_factory`
      delegates to `meshsa_core.mavlink.resolve_connection`; `meshsa-core` dependency pin
      added; **`docs/CHARTER.md` §3 amendment lands here** (design D-2's wording, alongside
      the dependency it describes — see T-0.2). Verification runs the soak suite.
- [ ] T-7.4 `bind_guard.LISTENER_TRIGGERS` gains `mavlink_connection`; jetson's bridge gets a
      guard or a declared governance exception; `command/mavlink_link.py` (frozen zone) gets
      a declared exception with rationale rather than a code change.

## Phase 8 — Command zone (gated; commanding stays disabled throughout)
- [ ] T-8.1 `Ack.from_message` classmethod on `command/lifecycle.Ack`; both call sites adopt
      it; the two call sites' different error-handling policies are kept and documented as
      deliberate (design D-7).
- [ ] T-8.2 Typing-only decoupling: `command/service.py` depends on a local
      `LinkHealthReport` Protocol instead of the concrete `fpv.link_health.HealthReport`;
      `command/mavlink_pump.py`'s link parameter is typed as the `CommandLink` Protocol;
      a `DrainableLink` Protocol replaces `getattr`-string capability detection.
- [ ] T-8.3 Denied commands become audited (design D-7, hardening #1); spec-delta scenario in
      `specs/agent-governance/spec.md`.
- [ ] T-8.4 Gate-issued `ConfirmedCommand` narrows `CommandSender.execute`; `build_command`
      becomes package-private (design D-7, hardening #2).
- [ ] T-8.5 `confirmation_ttl_s`/`pending_cap` config fields; TTL/cap enforcement; interlock
      re-run at confirm time for every command (design D-7, hardening #3).
- [ ] T-8.6 `command/lifecycle.py`'s ACK handling becomes a pure `classify(ack) -> Decision`
      enum (replacing three magic reason strings forwarded raw to the HTTP response);
      `command/config.py`'s `_BOUNDS` becomes `(name, requirement, predicate)` triples so a
      mismatch can't produce a `KeyError` at startup; `allowed` is validated against the known
      command set at startup (warn, matching the existing staging-time warn policy).
- [ ] T-8.7 `flightctl/run_commander.py`'s `build_app` adopts a `bearer_auth_middleware` +
      `_json_body` helper, replacing the three duplicated guard→parse→400 blocks; adopts
      `_web.py`'s response helpers (the 401-challenge-header delta is flagged for security
      review, same as T-3.1).
- [ ] T-8.8 `command/config.py` migrates to `_envconfig.py`; picks up
      `defaults.PORT_COMMANDER`; adopts `meshsa_core.mavlink.extract_endpoint_host` for its
      MAVLink endpoint; `HealthReport` import points at the T-5.2 neutral module (retiring
      the interim re-export).

## Phase 9 — Coupling fixes, non-command
- [ ] T-9.1 `build_node(..., codecs: Registry[Codec] = codec_registry)` — additive kwarg,
      symmetric with the existing `registry:` transport parameter; `scout/pipeline.py` takes
      an injected `codec: Codec | None = None`; `ui/cli.py`'s `_build_chat_agent` takes an
      injected agent factory and narrows its exception handling to `ImportError` (config/env
      failures are no longer silently swallowed alongside missing-extra failures).

## Phase 10 — Dead weight, sdnotify, docs, closeout
- [ ] T-10.1 The reviewed-but-unmerged sdnotify watchdog patch applied against real
      `meshsa.ui` code (`UIConfig.watchdog_heartbeat_s`, a heartbeat loop in `ui/cli.py`, the
      `Type=notify` unit moved to `ops/`, `sdnotify` added to the `ui` extra); tests exercise
      the real package code, not an inlined copy.
- [ ] T-10.2 `deliverables/meshsa-ui-validation/` retired (superseded patches deleted, tests
      already salvaged in T-1.1/T-3.1); `.gitleaks.toml`, `.dockerignore`, and pre-commit
      config cleaned of now-orphaned references.
- [ ] T-10.3 jetson reachability: `MavlinkPoseSource` wired into `build_pipeline` (with a test
      asserting `frame="local_ned"` yields a non-`None` pose source); `TimeSync.exchange`'s
      always-raising method deleted; the `jetson_gateway.yolo.json` detection-ingest config
      leg removed (no emitter exists for it) with a `NEXTSTEPS.md` Initiative-D item recording
      the decision.
- [ ] T-10.4 Remaining stale-doc claims corrected: `docs/AUDIT_M2_AUTH.md` residual rows,
      `NEXTSTEPS.md`'s stale G0.3 instructions (following them today would strict-XPASS the
      salvaged test), the `docs/C4.md`/`docs/architecture/C4.md` name collision (the former
      stays canonical), a pointer from the root `NEXTSTEPS.md` to `docs/NEXTSTEPS.md`,
      `netauth`'s `NetAuthPolicy` marked as a reserved seam, `tools/claude_hooks`' duplicated
      `sys.path` bootstrap consolidated, `validate_workforce.py` adopts `pyyaml` +
      `governance.find_repo_root`, `ops/pi5-node`'s duplicate STL/PNG files replaced with a
      README pointer to `hardware/usernode-stls/`.
- [ ] T-10.5 OpenSpec closeout: `gcp-drone-m2-agent-hardening`'s spec deltas promoted to
      `openspec/specs/`; both that bundle and this one archived; statuses moved to
      Implemented.

## Explicitly deferred (separate changes)
- Full `fpv/` tri-package split (`meshsa/crsf/`, `meshsa/linkhealth/`, `meshsa/flightlog/`) —
  pruned and decoupled in place instead (design D-1, D-9)
- `meshsa` test-tree reorganization beyond the mechanical `test_inference.py` split
- `flightctl/` console-script packaging (needs a systemd `ExecStart` migration decision)
- `command/mavlink_pump.py`'s hand-rolled reader thread vs. `transports/polling_source.py`
  (sync/threaded vs. asyncio Transport — unifying inside the frozen command zone is
  out of scope for this bundle)
- `command/health.py`'s `HeartbeatHealth` → `meshsa_core.heartbeat` unification (frozen zone;
  the freshness-predicate unification in T-5.3 covers the shared-logic risk without touching
  the frozen file's structure)
- Any Initiative-C commanding enablement — `c_gate_met` stays `false`
- `openspec` CLI in CI — not installed in this repo/CI (same deferral as
  `gcp-drone-m2-agent-hardening` T-1.2)
