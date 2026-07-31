# Changelog

All notable changes to this workspace are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versions follow [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

### Added

#### Charter alignment audit (2026-07-31)
- `docs/CHARTER_ALIGNMENT_AUDIT_PLAN.md` — repeatable Phase A–E method for scanning the codebase
  against `CHARTER.md` scope, all five ratified carve-outs, and all seven invariants in one pass;
  `docs/CHARTER_ALIGNMENT_AUDIT_PLAN_PEER_REVIEW.md` — its peer review (8 findings, all fixed).
- `docs/CHARTER_ALIGNMENT_AUDIT_2026-07-31.md` — the plan's first execution: a full gap-analysis
  pass (quality gates, magic-number sweep, bind/auth re-derivation, doc staleness) with 12
  findings, most fixed directly.
- `JetsonSettings` (`JETSON_*` env prefix) in `jetson_yolo_gcs/core/config.py`, and
  `PipelineSettings.fps_window` — closes three CHARTER §4 Invariant 5 (no magic numbers) gaps in
  `utils/jetson.py`/`utils/fps.py`/`pipeline.py`; defaults unchanged.
- `scripts/validate-pre-pr.sh::step_py_test_jetson` — the pre-PR gate now actually runs
  `packages/jetson_yolo_gcs`'s test suite; it was previously lint/type-checked but never pytest-run
  by this script.

### Fixed

#### Charter alignment audit (2026-07-31)
- `meshsa/netauth.py::validate_bind` now logs a structured warning before its fail-closed raise —
  previously silent except for the exception message; every one of its ~9 call sites benefits.
- `meshsa/ui/app.py`'s chat-handler JSON-parse swallow now logs like its six sibling handlers.
- `meshsa/transports/tak.py::_require_file`'s "not a regular file" branch was genuinely untested;
  added coverage. `meshsa/scout/__main__.py`'s untested entry shim now carries the same
  `# pragma: no cover` convention used elsewhere in the package.
- `docs/AUDIT_M2_AUTH.md` rows #10/#11 and two Gap-summary items described the pre-`fab3ab1`
  (2026-07-29) state (`mavlink_source` as fail-open, `detection_ingest` on port `8099`); corrected,
  and re-derived the true fail-open surface count (3, only 1 `bind_guard`-scoped).
- `docs/IMPLEMENTATION_PLAN.md` and `docs/ARCHITECTURE.md` cited a 2026-07-08 test-count snapshot
  against a materially different current tree; updated with fresh figures and an explicit
  snapshot-not-live-value caveat.
- `.gitignore` had no rule for `.claude/worktrees/` (Claude Code harness worktree state) and a
  blanket `.agents/` ignore that contradicted `.agents/skills/`'s real tracked status; both fixed.
- `README.md` never mentioned the Python drone-comms side of the repository; added a pointer.
- **`make typecheck`/`scripts/validate-pre-pr.sh` failed on every fresh clone.** `lib/api-zod` and
  `lib/db` are TS composite project references (`emitDeclarationOnly`) with gitignored `dist/`
  output and no `build` script; `api-server`'s typecheck needs that output to exist first. Added
  `"build": "tsc --build"` to both libs and a `pnpm --filter './lib/*' run build` prestep to both
  the Makefile and the validation script. Verified against a true fresh-clone simulation (both
  `dist/` and the gitignored `.tsbuildinfo` incremental cache removed).

### Added

#### Infrastructure & Tooling
- `docs/LOCAL_TESTING_PLAN.md` — comprehensive local test execution strategy, quality matrix, and peer review document
- `README.md` — root project overview, quick-start, architecture, contributing guide
- `CHANGELOG.md` — this file; standardised release tracking
- `NEXTSTEPS.md` — prioritised action backlog for workspace and GCP-Drone-Comms-Unit integration

#### `code-hygiene-modularity` program — gate widening (T-2)
- `.pre-commit-config.yaml` — the Python ruff / ruff-format / mypy hooks now scan repo-wide
  (`packages/`, `flightctl/`, `tools/`, `deliverables/`) instead of `deliverables/` only; the old
  scope silently skipped ~98% of tracked Python files from local pre-commit linting. The T-2.1
  commit fixes the fallout the widened scan surfaced (17 ruff findings, 6 reformats) in the same
  change so the gate lands green.
- `tools/claude_hooks/bind_guard.py` — the bind-safety scan (`SCAN_GLOBS`) now also covers
  `tools/**/*.py`, excluding `tools/**/tests/**` and `bind_guard.py` itself (its own fixtures
  and trigger-name constants would otherwise self-flag); `.claude/governance.yaml` documents the
  widened scope.
- `scripts/validate-pre-pr.sh` — gained real Python steps (`ruff check`, `ruff format --check`,
  `mypy`, `pytest` for `packages/meshsa`) ahead of the pre-existing `py_compile` syntax check, so
  the "full pre-PR gate" claim now actually exercises Python quality, not just TypeScript.
- `mypy.ini` — documented as the repo-wide root config (covering `packages/`, `flightctl/`,
  `tools/`) with per-package `pyproject.toml` overrides layered on top; the `--config-file` pin
  pre-commit previously passed mypy did not exist on disk and has been removed so mypy
  auto-discovers the correct config per invocation.
- `tools/claude_hooks/tests/test_bind_guard.py` — added regression coverage for the T-2.4
  scan-scope widening itself (`tools/**/*.py` inclusion, `tools/**/tests/**` exclusion, and the
  `bind_guard.py`-excludes-itself rule), which had shipped without direct tests.
- **The repo-wide `mypy` step had never completed a real run.** `python -m mypy packages/
  flightctl/ tools/ deliverables/` crashes immediately with `Duplicate module named "tests"`
  (mixing `tools/tests/` and `packages/jetson_yolo_gcs/tests/`, neither namespaced) — the
  broken `--exclude` above meant this was always the first thing hit, so it was never actually
  run to completion before now. Fixed: added `tools/__init__.py` (`tools.*` was already the
  import path every hook module uses; this makes `tools/tests` resolve as `tools.tests` instead
  of colliding with `jetson_yolo_gcs`'s bare `tests`) and split `scripts/validate-pre-pr.sh`'s
  type-check step into one `mypy src` pass per src-layout package (`packages/meshsa`,
  `packages/jetson_yolo_gcs` — each reads its own `pyproject.toml`, per `AGENTS.md`) plus a
  `flightctl/`+`tools/` pass and a `deliverables/` pass against the root `mypy.ini`: pytest's
  flat (no-`__init__.py`) test-collection convention means every package's `tests/` and
  `conftest.py` collide under one bare module name if mixed into a single mypy invocation.
  Running mypy against `deliverables/meshsa-ui-validation/` for the first time surfaced 14 real
  findings (9 stale/mismatched `# type: ignore` comments, 2 missing return-type annotations, 1
  missing `TestClient` generic type argument, 2 legitimate `attr-defined` on a not-yet-landed
  `UIConfig.watchdog_heartbeat_s` field pending the G0.1 patch) — all fixed in the same pass.
- **`.github/workflows/ci.yml` never actually ran the widened checks.** T-2.1/T-2.2 widened
  pre-commit and `validate-pre-pr.sh` to lint/type-check `tools/` and `deliverables/`, but CI's
  `test` job still only covered `packages/meshsa` + `flightctl` — so a violation in `tools/` or
  `deliverables/` would pass CI even though it would fail a local `pre-commit run --all-files`.
  CI's lint/format steps now cover `tools`/`deliverables` too, and two new steps
  (`mypy flightctl/ tools/`, `mypy deliverables/`) apply the same per-namespace split documented
  above; the `Install` step gained `pyyaml`/`types-PyYAML` (a `tools/claude_hooks` dependency
  that isn't part of `meshsa`'s own dependency set) so the new mypy steps can actually resolve
  `governance.py`'s `import yaml`.

#### Security & Hardening
- `MavlinkSourceTransport` network bind guard — endpoint host extraction and `validate_bind` fail-closed enforcement on non-loopback overrides
- `DetectionIngestTransport` port deconfliction — updated default UDP ingest port from `8099` to `8097` to eliminate port overlap with Scout station (`8099`)
- Cross-platform Node script execution — replaced POSIX-only preinstall script and added `LOG_LEVEL` environment variable fallback for Vitest in `artifacts/api-server/vitest.config.ts`
- `Makefile` — developer convenience targets: `dev`, `build`, `test`, `lint`, `typecheck`, `validate`, `clean`, `secrets-check`, `coverage`
- `Dockerfile` — multi-stage production build for `api-server`; non-root user, health check, minimal attack surface
- `.dockerignore` — excludes `node_modules`, `.git`, `deliverables/`, test output from Docker build context
- `eslint.config.js` — ESLint v9 flat config; TypeScript strict rules, no `console.*` (use `logger`), no hardcoded values guard, import ordering
- `vitest.config.ts` (root) — workspace-level Vitest configuration
- `artifacts/api-server/vitest.config.ts` — API server Vitest configuration with coverage thresholds
- `scripts/validate-pre-pr.sh` — full pre-PR gate: typecheck → lint → test → build → secrets scan
- `scripts/hooks/pre-commit` — git pre-commit hook enforcing typecheck + lint on staged TS files
- `.gitleaks.toml` — secret scanning rules; allowlists synthetic test tokens in `deliverables/`
- `.pre-commit-config.yaml` — pre-commit hooks for TypeScript (ESLint/tsc) and Python (ruff, mypy) sides
- `docs/architecture/C4.md` — C4 context, container, and component diagrams (Mermaid)
- `docs/adr/001-monorepo-typescript-esm.md` — ADR: pnpm workspace + TypeScript ESM + esbuild

#### Test Suite (AQA / Regression)
- `artifacts/api-server/src/__tests__/health.test.ts` — unit + integration tests for `GET /api/healthz`
- `artifacts/api-server/src/__tests__/app.test.ts` — middleware, CORS, JSON body parsing, 404 handling
- `artifacts/api-server/src/__tests__/logger.test.ts` — logger configuration, redaction, env-driven log level

#### meshsa.ui Validation Deliverables (`deliverables/meshsa-ui-validation/`)
- `docs/PEER_REVIEW.md` — polished peer review of the upstream validation plan; 3 false positives corrected, 3 missed gaps documented
- `tests/test_ui_validation_scenarios.py` — 6 named scenario tests (S1–S6): TTL eviction, composite-key concurrency, cap eviction ordering, kill-switch freeze, Cache-Control no-store, stale-token rotation
- `tests/test_mavlink_bind_guard.py` — Gate 0.3 bind-guard contract tests (xfail until patch applied)
- `tests/test_cli_sdnotify.py` — Gate 0.1 sd_notify heartbeat tests (xfail until patch applied)
- `tests/conftest.py` — shared pytest fixtures: `fake_clock`, `make_store`, `assert_geojson_feature_collection`
- `patches/cli_sdnotify_heartbeat.py` — sd_notify + watchdog instrumentation patch for `meshsa/ui/cli.py`
- `patches/mavlink_source_bind_guard.py` — `validate_bind` addition to `MavlinkSourceTransport.__init__`
- `systemd/meshsa-ui.service` — `Type=notify`, `WatchdogSec=30`, `Restart=on-failure`, `StartLimitBurst=5`
- `systemd/meshsa-ui.env.example` — all `MESHSA_UI_*` env vars with comments and defaults
- `docs/RESIDUAL_RISK_ADDENDUM.md` — R1/R2/R3 risk acceptance text for `operator-ui.md §6.1`
- `docs/PORT_DECONFLICTION_G02.md` — Port 8099 → 8101 deconfliction guide for `ScoutConfig`
- `pyproject-fragment.toml` — sdnotify dep, asyncio_mode, ruff/mypy config additions for target repo

### Changed

#### Hygiene / quality pass on validation deliverables
- `test_mavlink_bind_guard.py` — inlined `_parse_endpoint_host` + `_ENDPOINT_RE`; removed bad cross-directory import; added IPv6 non-match tests with rationale
- `test_cli_sdnotify.py` — inlined reference implementations; removed bad `patches/` import; `try/except (ImportError, AttributeError)`
- `cli_sdnotify_heartbeat.py` — moved `import pytest` to top (E402 fix); added `@pytest.mark.asyncio` to all async tests; rewrote as clean self-documenting patch module
- `mavlink_source_bind_guard.py` — changed lazy import to module-level import instruction; documented IPv6 rationale
- `meshsa-ui.env.example` — added `MESHSA_UI_WATCHDOG_HEARTBEAT_S=10` with WatchdogSec relationship comment
- `test_ui_validation_scenarios.py` — extracted coordinate magic numbers to `_DEFAULT_LAT/LON/HAE` constants; added full return type annotations; added docstrings to all builder helpers

### Updated

- `.gitignore` — added `dist/`, `coverage/`, `.vitest-cache/`, `*.tsbuildinfo`, `deliverables/**/__pycache__/`, `*.pyc`, `.pytest_cache/`
- `.agents/memory/MEMORY.md` — indexed `meshsa-ui-validation.md` topic file

### Security

#### `code-hygiene-modularity` program (`openspec/changes/code-hygiene-modularity/`)
- `meshsa.ui` — bearer-guarded `/api/*` JSON responses (`tracks`, `detections`, `health`, `fpv`, `chat`, `logs`) and the unauthorized/denied response bodies now carry `Cache-Control: no-store`; previously only the `/` page had it, so an intermediary proxy could persist an authorized JSON payload for replay to the next visitor of the same cached URL
- `meshsa.scout.station` — the operator page now pins MapLibre GL to an exact version with a Subresource Integrity hash (was a floating `@4` CDN reference with no integrity check) and escapes the injected bearer token against `</script>` termination (was bare `json.dumps`), matching `meshsa.ui`'s existing page hardening; both pages now share `meshsa._webpage`'s constants so they cannot drift apart again

### Fixed

#### `code-hygiene-modularity` program
- `meshsa.compact`'s codec-registry factory (`_make_compact`) discarded every keyword argument instead of forwarding them to `CompactCodec`, so a config-supplied `codec_options` value (e.g. a narrowed `supported_schemas`) was silently ignored for the compact codec alone
- `meshsa.llm.sources` — narrowed bare `except Exception` to `(aiohttp.ClientError, asyncio.TimeoutError, ValueError)` in `Mavlink2RestSource` and `FtsTrackSource`, preventing silent swallowing of logic errors and added structured `structlog.warning` before degraded returns
- **`--exclude` never actually excluded anything.** `scripts/validate-pre-pr.sh`'s Python steps
  (added in T-2.2) and the `.pre-commit-config.yaml` ruff/mypy hooks (widened in T-2.1) both
  passed/matched `tests/,archive/` — ruff's CLI splits `--exclude` on commas but a trailing `/`
  on each segment stops the pattern from matching, and pre-commit's `^tests/|^archive/` regex is
  anchored so it never matches a nested `tests/` directory (there is no top-level one). Net
  effect: the "exclude" was a silent no-op the whole time. Fixed to `--exclude archive` /
  `exclude: "^archive/"` (test directories are linted like the rest of the tree, matching
  `packages/meshsa`'s own `[tool.ruff.lint.per-file-ignores]` convention of scoping exceptions
  per-rule rather than exempting the directory outright). Widening the scan for real surfaced 8
  genuine findings (5 `SIM105`, 3 `SIM117`) in `deliverables/meshsa-ui-validation/{patches,tests}/`
  that were being silently skipped; fixed in the same pass.

### Changed — breaking default

#### `code-hygiene-modularity` program
- **`HealthConfig.port` default moved from `8088` to `8098`** (also `cli.py`'s `--healthz-port`/`HEALTHZ_PORT` default). `8088` is `mavlink2rest`'s own upstream convention; a node commonly wires a health listener and a `mavlink2rest`-backed LLM data source into the same process (`meshsa.ui.cli`), so meshsa should not claim a port an external tool already owns by convention. A deployment that relied on the old default must set `health.port: 8088` / `MESHSA_HEALTH_PORT=8088` explicitly to keep the old bind. New `meshsa.defaults` module centralizes `PORT_HEALTH` and other service-port constants (further consolidation of hardcoded ports across `ui`, `llm`, `commander`, `scout`, and `detection_ingest` is staged for T-3.5).

### Changed — operator-visible

#### `code-hygiene-modularity` program
- **`meshsa-scout` now honours `MESHSA_SCOUT_*` environment variables.** The standalone CLI previously built a bare `ScoutConfig()`, silently ignoring all 22 wired variables (`ScoutConfig` gains a new `from_env()` classmethod, sharing its scalar-override map with `NodeConfig.from_env().scout` so the two can never drift). **This is operator-visible, not just a bug fix:** a deployment that already exports `MESHSA_SCOUT_STORE_PATH` now gets a persistent file-backed store where it previously silently got the volatile `:memory:` default, and `MESHSA_SCOUT_STATION_TOKEN` now actually gates the station server where it was previously silently ignored. Operators who were relying on the old (unauthenticated / in-memory) behaviour should review their environment before upgrading.

---

## [0.1.0] — 2026-07-28

### Added

- Initial workspace scaffold: pnpm monorepo with `api-server` and `mockup-sandbox` artifacts
- Express 5 API server with pino structured logging, CORS, Drizzle ORM integration
- React 19 / Vite 7 / Tailwind 4 mockup sandbox with 50+ Radix UI components
- Shared libraries: `@workspace/db`, `@workspace/api-zod`, `@workspace/api-client-react`
- esbuild production bundler (`artifacts/api-server/build.mjs`)
- `scripts/post-merge.sh` — post-task-merge setup automation
- `pnpm-workspace.yaml` with catalog pinning and `minimumReleaseAge=1440` security policy
- `tsconfig.base.json` with strict TypeScript settings and project references
- Replit autoscale deployment configuration (`.replit`, `artifact.toml`)

[Unreleased]: https://github.com/ianshank/GCP-Drone-Comms-Unit/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/ianshank/GCP-Drone-Comms-Unit/releases/tag/v0.1.0
