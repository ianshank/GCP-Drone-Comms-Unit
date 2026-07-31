# Charter Alignment Audit — Plan

> **Status: WORKING PLAN (changeable).** This is a repeatable *method*, not a one-time result.
> It defines how an agent (or human) scans the codebase against [CHARTER.md](CHARTER.md) and
> reports drift. Running this plan produces a dated **findings report** (a separate document,
> `CHARTER_ALIGNMENT_AUDIT_<date>.md`); it does not itself amend CHARTER, ROADMAP, or
> governance state. Where a scan finds real drift, it is flagged for a maintainer §6 decision —
> never silently fixed by rewriting the charter or flipping a gate.

Reading order: [CHARTER.md](CHARTER.md) → [ROADMAP.md](ROADMAP.md) → [NEXTSTEPS.md](NEXTSTEPS.md)
→ [AUDIT_M2_AUTH.md](AUDIT_M2_AUTH.md) (auth posture, already covers Phase D below) →
[ROADMAP_RECONCILIATION.md](ROADMAP_RECONCILIATION.md) (prior scope-drift precedent) → this plan.

## Why this plan exists

The repo already carries several *partial* alignment checks: `AUDIT_M2_AUTH.md` (auth/encryption
surfaces only), `GAP_ANALYSIS.md` (test-category coverage only), `ROADMAP_RECONCILIATION.md`
(one external document reconciled once), and mechanical enforcement for two invariants
(`tools/claude_hooks/bind_guard.py`, `scope_freeze.py` via `.claude/governance.yaml`). Nothing
currently walks **every** CHARTER clause — §3 scope/non-goals, all six ratified carve-outs, and
all seven §4 invariants — against the current tree in one pass. This plan closes that gap and
gives future re-runs (a new feature branch, a maintainer pre-release check, a periodic sweep) a
fixed checklist instead of an ad hoc re-read of CHARTER.md.

## Ground truth at time of writing (2026-07-31)

- Governance: `c_gate_met: false` (`.claude/governance.yaml`) — Initiative-C command emission
  path (`packages/meshsa/src/meshsa/command/**`, `flightctl/run_commander.py`) stays frozen.
- `scope_widening_globs` (M3/M4 work barred during M2): `meshsa/federation/**`,
  `meshsa/storeforward/**` — neither directory exists in the tree yet (confirmed absent; this is
  the *expected* state, not a finding).
- Startup hook reports **5 fail-open surfaces** tracked in `AUDIT_M2_AUTH.md` — Phase D below
  re-derives that count against the live tree rather than trusting the cached figure.
- Six ratified CHARTER §3 carve-outs to check (dates from CHARTER.md): 2026-06-12 (ArmGuard
  pre-flight interlock), 2026-06-16 (Initiative-C supervised commanding), 2026-06-20 (on-board
  perception / `LANDING_TARGET`), 2026-07-05 (Scout offline survey export), 2026-07-16 (on-board
  tracker).

## Method

Each phase below names: the CHARTER clause it verifies, the concrete check, where in the tree to
run it, and which existing subagent (from the roster in `AGENTS.md` / `.claude/agents/`) is
scoped to do it — so execution can fan out instead of one agent reading the whole tree serially.

### Phase A — Scope conformance (CHARTER §3, in-scope / non-goals)

Verify the tree only contains the four in-scope areas (`meshsa`, `flightctl`, `hardware`,
`jetson_yolo_gcs`) and none of the explicit non-goals have crept in.

1. Confirm no code path *flies or controls* the aircraft outside the six ratified carve-outs —
   grep for MAVLink `COMMAND_LONG`/`COMMAND_INT`/RC-override sends outside
   `meshsa/command/**`, `meshsa/fpv/arm_guard.py`, and `jetson_yolo_gcs/mavlink/bridge.py`.
2. Confirm the ATAK Android app is not vendored or built from this repo (docs/ops references
   only).
3. Confirm no general-purpose message-broker surface exists (i.e. no new pub/sub facing
   arbitrary topics/consumers outside `Router`/`transport_registry`).
4. Confirm `meshsa/federation/**` and `meshsa/storeforward/**` (M4, explicitly out of scope
   during M2 per `scope_widening_globs`) remain absent or, if present, are flagged immediately —
   this is a hard stop, not a soft finding.
5. Confirm the four in-scope directories (`packages/meshsa`, `flightctl`, `hardware`,
   `packages/jetson_yolo_gcs`) account for all shipped functionality; anything else under
   `packages/` or a new top-level service directory needs a scope justification.

Owner: general sweep (Explore/general-purpose agent); escalate any hit to a human per CHARTER §6.

### Phase B — Carve-out compliance (CHARTER §3 amendments)

For each ratified carve-out, check its own stated constraints against the current code, not
just that the feature exists.

| Carve-out | Constraint to verify | Where to look |
| --- | --- | --- |
| ArmGuard pre-flight interlock (2026-06-12) | Never touches the arm channel after it goes high; latch resets only on operator-driven disarm; no other RC channel is ever written | `packages/meshsa/src/meshsa/fpv/arm_guard.py`, `fpv/config.py`, `fpv/errors.py` |
| Initiative-C supervised commanding (2026-06-16) | `c_gate_met` still `false`; command path only reachable via `transport_registry`/command codec, not router/node edits; `COMMAND_INT` + bounded-retry `ACK`; force-disarm path (param2=21196) gated behind separate confirmation and off by default; `meshsa.llm` issues no commands | `.claude/governance.yaml`, `packages/meshsa/src/meshsa/command/*.py` (safety.py, audit.py, commands.py, service.py), delegate to **charter-gate-keeper** |
| On-board perception / `LANDING_TARGET` (2026-06-20) | `MavlinkSettings.enable_landing_target` defaults `false`; publisher never arms/sets-mode/sends RC; detector/camera/stream/MAVLink seams stay `Protocol`-based | `packages/jetson_yolo_gcs/src/jetson_yolo_gcs/core/config.py:88`, `mavlink/bridge.py` |
| Scout offline survey export (2026-07-05) | No auto-upload, no MAVLink writes, no in-flight action anywhere in `meshsa/scout/**`; output is a file only | `packages/meshsa/src/meshsa/scout/export_mission.py`, `scout/cli.py`, `scout/pipeline.py` |
| On-board tracker (2026-07-16) | `TrackerSettings.enabled` defaults `false`; tracker output feeds only the health snapshot (`tracks_active`/`tracks_total`/`dropped_tracks`), never `LANDING_TARGET` selection or a command; frozen `Detection` is not mutated (wrapped in `TrackedDetection`) | `packages/jetson_yolo_gcs/src/jetson_yolo_gcs/core/config.py` (`TrackerSettings`), `tracking/factory.py`, `tracking/norfair_backend.py` |

Owner: **charter-gate-keeper** for the Initiative-C row; general sweep for the other four
(none of the other five subagents have standing scope over `fpv/`, `scout/`, or `tracking/`).

### Phase C — Invariant conformance (CHARTER §4, all seven)

| # | Invariant | Check | Owner |
| - | --- | --- | --- |
| 1 | Open/closed extensibility via registries | New transports/codecs register through `transport_registry`/`codec_registry`; `router.py`/`node.py`/`models.py` diffs since the last release don't add per-medium branching | general sweep |
| 2 | Versioned wire (`schema_version`) | Every `Envelope` still carries `schema_version`; peers gate on `[MIN_COMPATIBLE_SCHEMA, SCHEMA_VERSION]`; any envelope-shape change in the diff has a matching version bump + CHANGELOG entry | general sweep |
| 3 | `Protocol`-based DI | `Transport`/`Codec`/`Clock`/`IdFactory` remain structural `Protocol`s; unit tests use fakes, not live sockets/radios | general sweep, spot-check against `.agents/skills/meshsa-test-conventions` |
| 4 | Stateful I/O in transports, not codecs | Codecs stay pure per-frame maps; no codec opens a socket/file | general sweep |
| 5 | Config-driven, no magic numbers | Every operational value is a config field with a default; no bare literals for ports/hosts/intervals in diffs | **config-guardian** |
| 6 | Quality gates green | `ruff check .`, `ruff format --check .`, `mypy --strict` (`src`), `pytest` all green in both `packages/meshsa` and `packages/jetson_yolo_gcs`; hardware/socket glue is the only `# pragma: no cover` | run from each package dir per `AGENTS.md`/CLAUDE.md; **test-engineer** for coverage-floor questions |
| 7 | No secrets / machine fingerprints | `.gitleaks.toml` scan clean; no committed `*.env` with real values, no hostnames/serials baked into source | `pre-commit` / gitleaks run |

### Phase D — Network bind / auth posture (cross-cutting, feeds Invariant 6 + M2 security invariant)

Re-derive the fail-open surface count instead of trusting the cached "5" from the startup hook:
walk every socket bind in `packages/**/src/**/*.py`, `flightctl/*.py`, `tools/**/*.py` against
`meshsa.netauth.validate_bind`, cross-checked with `bind_guard.exceptions` in
`.claude/governance.yaml`, and reconcile against `AUDIT_M2_AUTH.md`'s existing surface table
(update it if the tree has moved since 2026-07-08; do not fork a duplicate table).

Owner: **bind-auditor** (primary), **security-reviewer** (fail-closed posture verification).

### Phase E — Roadmap/backlog consistency (not CHARTER itself, but must not silently diverge)

1. `NEXTSTEPS.md` checklist items map to a ROADMAP milestone/initiative that actually exists;
   nothing there opens M3+ scope early or contradicts a §3 non-goal.
2. `openspec/changes/*` bundles (currently `code-hygiene-modularity`,
   `gcp-drone-m2-agent-hardening`) don't propose anything that would require a CHARTER
   amendment without flagging it as such.
3. `docs/specs/` status column (Definition/Implemented/Validated) matches what's actually in the
   tree for each initiative spec.

Owner: general sweep.

## Deliverable

A single dated report, `docs/CHARTER_ALIGNMENT_AUDIT_<YYYY-MM-DD>.md`, structured as:

1. Summary table — one row per phase (A–E), verdict (`Aligned` / `Drift found` / `Needs
   maintainer decision`), and a one-line reason.
2. Per-finding detail — CHARTER clause cited, code location (`module.py::symbol`, never a bare
   line number per the `charter-gate-keeper` citation convention), severity, and recommended
   next step (fix directly vs. escalate per §6).
3. No finding gets auto-fixed *and* silently closed in the same report — a code fix is a
   separate diff/PR that this report links to, so the report stays an honest snapshot.

## Cadence

- Run Phases A–C, E on any branch that touches `docs/CHARTER.md`, `docs/ROADMAP.md`, adds a new
  top-level package/service, or precedes a release tag.
- Run Phase D whenever a diff touches a socket bind, transport, or `packages/meshsa/src/meshsa/netauth.py`
  (this already overlaps `bind-auditor`'s and `security-reviewer`'s standing trigger rules — no
  new automation needed, just remember to fold results into the dated report).
- A full A–E pass is otherwise a maintainer-triggered periodic sweep, not a per-PR gate — the
  existing per-diff subagents already cover the hot paths continuously.

## Explicit non-goals of this plan

- Does not flip `c_gate_met` or edit `.claude/governance.yaml` — that stays a maintainer §6
  decision per `charter-gate-keeper`'s standing refusal list.
- Does not amend CHARTER.md/ROADMAP.md itself. Drift found here is a decision for a human, not a
  patch applied by whichever agent ran the scan.
- Does not replace `AUDIT_M2_AUTH.md`, `GAP_ANALYSIS.md`, or `ROADMAP_RECONCILIATION.md` — it
  cites and reuses them (Phase D, Phase C.6, Phase E) rather than re-deriving what they already
  cover.
