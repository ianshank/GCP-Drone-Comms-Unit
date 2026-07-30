# OpenSpec Change: Code Hygiene & Modularity Program

- **change_id**: `code-hygiene-modularity`
- **project**: GCP-Drone-Comms-Unit (repository `ianshank/GCP-Drone-Comms-Unit`)
- **status**: accepted — implemented by the PR that materializes this bundle
- **milestone**: M2-adjacent hygiene/hardening enabler. Does **not** open M3/M4/M5 and does
  **not** clear the Initiative-C command gate (`c_gate_met` stays `false`).
- **authoritative sources**: `docs/CHARTER.md`, `docs/ROADMAP.md`, `docs/AUDIT_M2_AUTH.md`,
  `AGENTS.md`, `.claude/governance.yaml`, `docs/specs/README.md`
- **peer review**: `docs/OPENSPEC_CODE_HYGIENE_PEER_REVIEW.md` (this bundle's design was
  reviewed against `docs/CHARTER.md`, the `bind_guard.py` adapter rule, and Invariants 1–2
  before implementation; thirteen corrections were made to the pre-review draft — five of
  them defects the draft itself introduced, including a would-be Invariant-1 violation)

## Why

Five audit sweeps (meshsa core; jetson_yolo_gcs/flightctl/tools; repo/workspace level; the
`fpv` subsystem; `llm`/`command`/`scout`) plus hands-on verification against the running test
suites found four classes of debt in a codebase that is otherwise unusually disciplined
(zero `TODO`/`FIXME` markers, real `Protocol` seams, no orphaned modules):

1. **Quality gates that don't gate.** `.pre-commit-config.yaml` scopes ruff/format/mypy to
   `^deliverables/.*\.py$` — 273 of 279 tracked Python files are never linted locally, proven
   live by two `F401` errors sitting uncaught in `tools/claude_hooks/governance.py`. No CI job
   runs `pnpm typecheck/lint/test` for the 86-file TypeScript half of the repo.
   `scripts/validate-pre-pr.sh` claims to be "every check that must pass before a pull request
   is opened" but runs no Python tests at all.
2. **Security-relevant duplication that has already drifted.** Four `aiohttp` app factories
   (`ui/app.py`, `scout/station/app.py`, `health.py`, `llm/server.py`) independently
   re-implement the bearer-auth guard, the `?token=` navigation gate, and the `/healthz`
   handler; only `health.py` sends the `WWW-Authenticate` challenge. The scout operator page
   (`scout/station/_html.py`) has lost the SRI pinning and script-safe token escaping that its
   sibling page (`ui/_html.py`) documents as a deliberate defense against exactly the CDN
   supply-chain and script-injection risk the scout page is now exposed to. Four independent
   copies of the "is this health report fresh enough to arm" predicate use three different
   time windows (1.0s / 2.0s / 3.0s bare literal).
3. **Six verified bugs**, including bearer-authorized JSON API responses with no
   `Cache-Control` header (cacheable by any intermediary proxy despite the auth), a codec
   factory that silently discards a caller-supplied `codec_options` value, and health/UI/
   mavlink2rest defaulting to the same port (`8088`) in a configuration the code provably
   wires into one process.
4. **Fail-closed gaps on the governance-frozen command path** (`packages/meshsa/src/meshsa/command/`):
   a denied command (unknown command, disallowed command, blocked force-disarm) leaves no
   audit record; `CommandSender.execute` type-accepts a `CommandSpec` that never passed the
   confirmation gate; staged commands never expire or get garbage-collected.

Baseline is fully green before this change lands: meshsa 1,086 tests passed / 6 skipped
(`--cov-fail-under=97`), `jetson_yolo_gcs` 205 tests passed (`--cov-fail-under=96`), both
`mypy --strict` clean. The refactor safety net this program relies on is real, not aspirational.

## What Changes

- **New shared modules** under `packages/meshsa/src/meshsa/`: `_web.py` (fail-closed aiohttp
  auth/response kit), `_envconfig.py` (generic env-loader), `_frame_codec.py` (shared
  frame-decode scaffold), `_webpage.py` (SRI-pinned page fragments), `_geojson.py`
  (finite-value-guarded GeoJSON), `_queues.py` (`BoundedDropQueue`), `defaults.py`
  (operational-default constants + service-port table), `mavlink_constants.py`,
  `_logging.py` (a dependency-free leaf so `fpv/tools/*` stop importing the `meshsa` package
  root).
- **New distribution `packages/meshsa_core`** (import name `meshsa_core`): the primitives
  `jetson_yolo_gcs` currently forks byte-for-byte (`Clock`, `Registry`, logging setup,
  heartbeat gating, MAVLink connection-factory glue) plus `meshsa.netauth`, extracted to one
  place both packages depend on. Both packages adopt it through explicit re-export shims —
  every existing public import path keeps working.
- **Class splits behind unchanged public facades**: `InferenceService`, `TakTcpTransport`
  (+ `TakMulticastTransport` moved to its own module), `FlightLogger`, `CotCodec`, the jetson
  `LandingTargetBridge`/`Pipeline`, and `run_commander.build_app`.
- **Gate widening**: pre-commit runs repo-wide (not `deliverables/`-only); a new CI job
  enforces the TypeScript workspaces; `scripts/validate-pre-pr.sh` gains real Python steps;
  `bind_guard.py`'s scan globs extend to `flightctl/` and `tools/` (excluding the linter's own
  test fixtures — see design D-9).
- **`fpv/` prune and decouple**: verified-dead surface removed (with a CHANGELOG entry);
  surface backed by the ratified 2026-06-12 arm-gating carve-out is explicitly kept and
  marked, not deleted (see design D-1); the `HealthReport`/`HealthState` types move to a
  neutral module, closing a latent package-init import cycle; the three-way freshness-gate
  duplication collapses to one predicate.
- **`scout`/`llm` correctness fixes**: the sqlite store moves off the aiohttp event loop and
  gains an atomic status update; the pose/detection alignment window stops resetting every
  `ingest()` call; DEM failures fail closed instead of silently downgrading to flat-earth;
  the LLM agent handles non-`tool_use` stop reasons instead of rendering an empty chat bubble.
- **Command-zone hardening** (gated, see design D-1 and D-5): denied commands become audited;
  `ConfirmedCommand` becomes a gate-issued type so `execute()` cannot accept an unconfirmed
  spec; staged commands gain a TTL and a pending-count cap. Commanding stays disabled
  throughout — none of this touches `c_gate_met` or ships a command entry point.
- **Dead-weight retirement**: the `deliverables/meshsa-ui-validation/` scratch tree (superseded
  patches + salvageable tests); the unconsumed `artifacts/mockup-sandbox` and
  `lib/api-client-react` TypeScript workspaces (archived, not deleted); stale claims in
  `docs/AUDIT_M2_AUTH.md` and `NEXTSTEPS.md`.
- **The reviewed-but-never-merged `sdnotify` watchdog patch is applied** against real package
  code (`meshsa.ui`), replacing the deliverables tree's tautological tests of an inlined copy.

## Scope — what this change is NOT

- **No Initiative-C commanding enablement.** `c_gate_met` is not touched and no command
  console-script/systemd entry point ships. The command-zone tasks in this bundle *harden*
  the existing gate (audit trail, unforgeable confirmation, bounded staging) — the same
  posture as the `gcp-drone-m2-agent-hardening` precedent, which built the gate rather than
  opening it.
- **No envelope/`schema_version` change.** No task in this bundle touches `Envelope` shape;
  the full version-bump ritual is never triggered.
- **No new network surface.** Every touched surface already exists; the change closes gaps
  and consolidates duplicated auth scaffolding, it opens nothing.
- **No retirement of charter-ratified capability.** The 2026-06-12 pre-flight arm-gating
  carve-out (`ArmGuard`, the CRSF RC transmit path) is explicitly out of scope for deletion —
  see design D-1. Retiring ratified capability is a `§6` human decision, not a hygiene task.
- **No change to transport registration semantics.** `transports/__init__.py`'s
  import-time registration (Invariant 1) is preserved exactly — see design D-9.
- **No M3/M4/M5 features, no mission/autonomy scope expansion.**
- **No full test-tree reorganization** — only the mechanical split of
  `tests/test_inference.py` (1,195 lines) that accompanies the `InferenceService` split.
- **No flightctl console-script packaging** — the `pythonpath` bridge that makes
  `flightctl/run_commander.py` importable from `packages/meshsa/tests/` stays as-is; proper
  packaging is a separate maintainer decision (systemd `ExecStart` migration required).
- **No `fpv/` tri-package split** (`meshsa/crsf/`, `meshsa/linkhealth/`, `meshsa/flightlog/`)
  — pruned and decoupled in place instead; the larger restructure is deferred.

## Invariants (binding on every task)

| # | Invariant | Source | Enforcement |
|---|---|---|---|
| I-1 | Transport/codec registration stays import-time; no lazy-registration change | `CHARTER.md` §4 Invariant 1; `transports/__init__.py` docstring | design D-9; review |
| I-2 | Every network surface keeps failing closed; the bind-guard single-primitive rule holds through the `netauth` move | `CHARTER.md` §4 Invariant 6; `.claude/governance.yaml` | `bind_guard.py` CI + governance hook tests |
| I-3 | Config-driven, no magic numbers — new defaults live in `defaults.py`/config fields, not literals | `CHARTER.md` §4 Invariant 5 | review + config-guardian |
| I-4 | Full test suite; coverage gates hold (meshsa 97%, jetson 96%); no mocked fail-closed assertions | `AGENTS.md`; package `pyproject.toml` addopts | CI |
| I-5 | Command-zone edits stay behavior-preserving or explicitly hardening; `c_gate_met` untouched | `CHARTER.md` §3 Initiative-C carve-out; `.claude/governance.yaml` scope-freeze | `charter-gate-keeper` + `security-reviewer` sign-off per commit |
| I-6 | Ratified charter carve-out code is never silently deleted | `CHARTER.md` §3, §6 | design D-1; review |
| I-7 | Backwards compatible: every existing public import path keeps resolving | design D-2 (re-export shims) | mypy `--strict` (`no_implicit_reexport`) + full suite |

## Impact

- **Affected specs**: `m2-bind-safety` (modified + added requirements), `agent-governance`
  (added requirements), `meshsa-core` (new capability, this bundle)
- **Affected code**: see design.md's per-task file list; summary — new `packages/meshsa_core/`;
  new `meshsa/_web.py`, `_envconfig.py`, `_frame_codec.py`, `_webpage.py`, `_geojson.py`,
  `_queues.py`, `defaults.py`, `mavlink_constants.py`, `_logging.py`; class-split facades in
  `inference.py`, `transports/tak.py`, `fpv/flight_logger.py`, `cot.py`; `fpv/` prune;
  `scout/store.py`, `scout/pipeline.py`, `scout/terrain.py`; `llm/agent.py`, `llm/sources.py`,
  `llm/tools.py`; `command/` (gated, see tasks T-8); `jetson_yolo_gcs` bridge/pipeline +
  `meshsa_core` adoption; `.pre-commit-config.yaml`, `.github/workflows/ci.yml`,
  `scripts/validate-pre-pr.sh`; `.claude/governance.yaml`; `docs/CHARTER.md` §3 (jetson
  dependency amendment, landed alongside the actual dependency in task T-7.3).
- **Affected behavior at runtime**: `Cache-Control: no-store` and `WWW-Authenticate` headers
  appear on surfaces that lacked them; `meshsa.ui`'s health-listener default port moves
  `8088` → `8098`; `meshsa-scout` starts honoring 22 previously-ignored `MESHSA_SCOUT_*`
  environment variables (operator-visible — an already-set `MESHSA_SCOUT_STORE_PATH` now
  takes effect); `meshsa.ui` gains an opt-in systemd watchdog heartbeat. No other externally
  observable behavior changes; read-only-by-default posture is preserved throughout.
