# Next Steps

Prioritised backlog for this workspace and the
[GCP-Drone-Comms-Unit](https://github.com/ianshank/GCP-Drone-Comms-Unit) integration.

This file tracks the **TypeScript/Replit validation workspace** (Tracks 1-4 below). The
Python drone-comms side (`packages/`, `flightctl/`, `openspec/`) has its own backlog at
[docs/NEXTSTEPS.md](docs/NEXTSTEPS.md).

Items are grouped by **track** and ordered by priority within each track.
`[ ]` = open, `[x]` = complete.

---

## Track 1 — Workspace infrastructure

### P0 — Blocking CI / quality gate

- [ ] **Install test + lint dependencies** (`pnpm install` after package.json updates)
  — vitest, @vitest/coverage-v8, supertest, @types/supertest, eslint, @typescript-eslint/*
  — Required for `make validate` to pass
- [ ] **Wire git hooks** — run `scripts/hooks/install-hooks.sh` once per clone
  to symlink `scripts/hooks/pre-commit` into `.git/hooks/`
- [ ] **Run full validation gate** — `make validate` must exit 0 before any PR

### P1 — Coverage & reliability

- [ ] **Expand test suite** — currently covers health route, middleware, logger;
  add tests for any new routes as they are added
- [ ] **Set up DB integration tests** — stub the Drizzle client in tests with
  `vi.mock('@workspace/db')` rather than hitting a live DB in CI
- [ ] **Add `test:watch` script** to `api-server` package.json for TDD workflow

### P2 — Developer experience

- [ ] **GitHub Actions workflow** — `.github/workflows/validate.yml`; runs
  `make validate` on every PR and push to `main`
- [ ] **Renovate / Dependabot** — automated dependency update PRs with the
  existing `minimumReleaseAge=1440` policy enforced
- [ ] **VSCode workspace settings** — `.vscode/settings.json` for consistent
  editor config (eslint, format-on-save, TypeScript project references)

---

## Track 2 — meshsa.ui validation (GCP-Drone-Comms-Unit)

### P0 — Blocking `Validated` status on the operator-ui spec

- [ ] **Apply G0.1 sd_notify patch** to `packages/meshsa/src/meshsa/ui/cli.py`
  — Follow `deliverables/meshsa-ui-validation/patches/cli_sdnotify_heartbeat.py`
  — Add `watchdog_heartbeat_s: float = Field(default=10.0, gt=0.0)` to `UIConfig`
  — Add `sdnotify>=0.3` to `[project.optional-dependencies] ui` in `pyproject.toml`
  — Tests: `test_cli_sdnotify.py` xfails must flip to xpass

- [x] **G0.3 mavlink bind guard — already shipped, patch retired.**
  `transports/mavlink_source.py`'s `MavlinkSourceTransport` extracts the endpoint host and
  validates binds via `netauth.validate_bind` (landed 2026-07-24, predates this deliverable's
  patch). The `deliverables/meshsa-ui-validation/patches/mavlink_source_bind_guard.py` patch and
  its `test_mavlink_bind_guard.py` xfail test were **deleted** (`code-hygiene-modularity` T-10.2a):
  the patch's regex endpoint parser failed open on bracketed IPv6, so the shipped guard is
  stricter, not merely equivalent. Its empty/whitespace-token assertions were salvaged into
  `packages/meshsa/tests/test_mavlink_source.py` first.

- [ ] **Drop in scenario tests** — copy all test files from `deliverables/meshsa-ui-validation/tests/`
  into `packages/meshsa/tests/`; run `pytest tests/ -v --cov=meshsa --cov-fail-under=97`

### P1 — Required before field validation (Gate 3)

- [ ] **Apply G0.2 port deconfliction** — change `ScoutConfig` default port 8099 → 8101
  — Follow `deliverables/meshsa-ui-validation/docs/PORT_DECONFLICTION_G02.md`

- [ ] **Insert residual risk documentation** into `docs/specs/operator-ui.md §6.1`
  and `docs/AUDIT_M2_AUTH.md` surface #17 — use
  `deliverables/meshsa-ui-validation/docs/RESIDUAL_RISK_ADDENDUM.md` verbatim

- [ ] **Deploy systemd unit** to target edge hardware
  — `flightctl/systemd/meshsa-ui.service` from deliverables
  — Fill in `MESHSA_UI_TOKEN` in `/etc/flightctl/meshsa-ui.env`
  — Verify `systemctl status meshsa-ui` shows `active (running)` with sd_notify

### P2 — After field validation passes

- [ ] **Implement `X-Snapshot-Age` response header** in `meshsa.ui.app`
  — Add `SnapshotStore.newest_ts() -> float | None`
  — Flip the S4d xfail in `test_ui_validation_scenarios.py` to a passing test
  — Spec amendment: add to `operator-ui.md §7` exit criteria

- [ ] **Open PR against GCP-Drone-Comms-Unit `main`** with all Gate 0–2 changes,
  referencing `deliverables/meshsa-ui-validation/README.md` as the PR description base
  — PR must have all scenario tests green and no xfails remaining except S4d

- [ ] **Tick `NEXTSTEPS.md` items** in the target repo after each gate passes
  — systemd + sd_notify open item
  — Port 8099 deconfliction
  — Residual risk records

---

## Track 3 — API server roadmap

- [ ] **Database schema** — define initial Drizzle tables in `lib/db/src/schema/`
  matching the intended application domain
- [ ] **Authentication** — integrate session middleware with `SESSION_SECRET`;
  follow `better-auth-best-practices` skill if using Better Auth
- [ ] **API versioning** — prefix routes with `/api/v1/` before any public endpoints
  are shipped; add version header to all responses
- [ ] **Request validation** — enforce Zod schema parsing on all request bodies
  via a shared `validateBody` middleware; return 400 with field-level errors
- [ ] **Error handling** — add a global Express error handler that logs with
  `logger.error` and returns structured JSON (`{ error: string, code: string }`)
- [ ] **Rate limiting** — add `express-rate-limit` before auth endpoints

---

## Track 4 — Security hardening

- [ ] **CORS origin allowlist** — replace the open `cors()` middleware with an
  explicit origin list from `ALLOWED_ORIGINS` env var
- [ ] **Helmet.js** — add HTTP security headers (`X-Frame-Options`, `HSTS`,
  `Content-Security-Policy`, `X-Content-Type-Options`)
- [ ] **Secrets audit** — run `make secrets-check` after every PR; review the
  `.gitleaks.toml` allowlist quarterly to ensure no real tokens are exempted
- [ ] **Dependency audit** — run `pnpm audit --audit-level=high` monthly;
  integrate into `make validate` once CI is wired

---

## Completed

- [x] Initial monorepo scaffold (pnpm, TypeScript, ESM)
- [x] Express 5 API server with pino logging and CORS
- [x] React 19 / Vite 7 mockup sandbox
- [x] Shared libraries (db, api-zod, api-client-react)
- [x] meshsa.ui peer review + rewritten validation plan
- [x] All 6 named scenario tests (S1–S6)
- [x] Gate 0–2 patch files and documentation
- [x] Residual risk acceptance text (R1/R2/R3)
- [x] Systemd unit with WatchdogSec + sd_notify
- [x] Code hygiene pass: E402 fixes, type annotations, module constants, inlined helpers
