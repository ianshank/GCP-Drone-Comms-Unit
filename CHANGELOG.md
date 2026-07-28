# Changelog

All notable changes to this workspace are documented here.  
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).  
Versions follow [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

### Added

#### Infrastructure & Tooling
- `README.md` — root project overview, quick-start, architecture, contributing guide
- `CHANGELOG.md` — this file; standardised release tracking
- `NEXTSTEPS.md` — prioritised action backlog for workspace and GCP-Drone-Comms-Unit integration
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
