# Changelog

All notable changes to this workspace are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versions follow [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

### Added

#### Infrastructure & Tooling
- `docs/LOCAL_TESTING_PLAN.md` — comprehensive local test execution strategy, quality matrix, and peer review document
- `README.md` — root project overview, quick-start, architecture, contributing guide
- `CHANGELOG.md` — this file; standardised release tracking
- `NEXTSTEPS.md` — prioritised action backlog for workspace and GCP-Drone-Comms-Unit integration

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
