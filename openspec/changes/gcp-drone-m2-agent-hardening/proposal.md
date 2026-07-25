# OpenSpec Change: Agent-Driven M2 Hardening

- **change_id**: `gcp-drone-m2-agent-hardening`
- **project**: GCP-Drone-Comms-Unit (repository `ianshank/GCP-Drone-Comms-Unit`)
- **status**: accepted — implemented by the PR that materializes this bundle
- **milestone**: M2 (Hardening & productization) — closes the open items, does
  **not** open M3/M4 or clear the Initiative-C gate
- **authoritative sources**: `docs/CHARTER.md`, `docs/ROADMAP.md`,
  `docs/NEXTSTEPS.md`, `docs/AUDIT_M2_AUTH.md`, `docs/IMPLEMENTATION_PLAN.md`
- **peer review**: `docs/OPENSPEC_M2_BUNDLE_PEER_REVIEW.md` (rev.1 was corrected
  against the tree before implementation)

## Why

Two facts define this change:

1. **The M2 gate is nearly closed, and precisely documented.**
   `AUDIT_M2_AUTH.md` is a 16-row inventory (12 of them network-bound surfaces;
   the rest serial links, a non-network helper, and one listener that turned
   out not to exist) with per-row default bind + port, auth, encryption, and
   fail-closed status. Four HTTP surfaces already share the audited
   `netauth.validate_bind` primitive and fail closed. The remaining gaps are
   named, not vague — an execution problem, not a discovery problem.
2. **This repo is majority agent-authored.** [Certain] `git shortlog -sn`:
   Reorg Agent 68, Claude 67, Ian Cruickshank 49 — agents wrote ~73% of
   commits. Turning more agents loose without a mechanical scope boundary is
   the specific risk to a codebase whose distinguishing asset is a security
   invariant enforced in code (ROADMAP M2: "no unauthenticated surface is
   exposed by default"). This change therefore ships the enforcement *before*
   the agents.

## What Changes

- **Bootstrap OpenSpec + a subagent roster** (`.claude/agents/`) that
  collaborate by default, each scoped to M2 hardening — defined as thin
  wrappers over the roles the repo already has in `.github/agents/*.agent.md`
  and `.agents/skills/`, not a parallel hierarchy (design D-1).
- **Add mechanical guardrails as hooks** (extending the existing `SessionStart`
  hook additively): a **scope-freeze gate** (deny edits widening scope past M2
  or touching the Initiative-C command surface while its gate is unmet) and a
  **bind-guard linter** (CI fails if any network surface lacks a fail-closed
  bind check, or re-implements `validate_bind` outside `meshsa.netauth`).
- **Close the named fail-open gaps**: audit surfaces #10 and #14, the
  transport-wide-auth seam, and the commander's duplicated weaker
  `validate_bind` (found in review; design D-3.3) — each with tests.
- **Give `netauth` its own direct test file** — it had none; it was tested
  only through its callers.
- **Add `.mcp.json`** with GitHub MCP only (PR/issue ops); no others.
- **Build the link-loss resilience soak** queued as `m2-soak-fuzz.md` and
  listed in ROADMAP M2 ("soak/fuzz on real radios"). Link-layer denial
  (deauth on 802.11-class links, jamming) is an *availability* attack that
  TLS/endpoint-auth do not address; the untested surface was fail-closed
  behavior under sudden link loss.

## Scope — what this change is NOT

- **No Initiative-C commanding work.** [Certain] `NEXTSTEPS.md` — "do not
  ship a command surface before TLS + auth land." The command stack is
  implemented and unit-tested (`meshsa.command.*`, nine test modules) but has
  no console-script entry point and no systemd unit; gate clearance is a
  maintainer decision per the repo's §6 ratification convention. This change
  *builds the gate that enforces that*, hardens the commander's bind guard
  (a fail-closed fix, not an enablement), and adds gate tests; it does not
  extend, enable, or ship commanding.
- **No M3/M4/M5 features** (richer tracks, fleet, packaging).
- **No perception/Scout capability code** (Initiatives D/Scout HW paths stay
  in `docs/specs/`).
- **No new network surface.** The change closes surfaces; it opens none.

## Invariants (binding on every task)

| # | Invariant | Source | Enforcement |
|---|---|---|---|
| I-1 | No unauthenticated surface by default — every network-facing surface fails closed on non-loopback bind without a credential | `ROADMAP.md` M2 security invariant; `CHARTER.md` commanding carve-out | `bind_guard.py` CI linter + per-surface tests |
| I-2 | Backwards compatible: additive to `docs/specs/`, `.claude/settings.json`, `AGENTS.md`; OpenSpec added beside, not replacing | — | `tools/validate_workforce.py` + review |
| I-3 | No hardcoded values: ports, tokens, intervals, bind hosts are config fields (repo Ruff selects `E,F,I,UP,B,SIM`; no-magic-numbers stays prose policy, CHARTER §5 — widening to `PL` is a separate maintainer decision) | `CHARTER.md` §5 | review + config-guardian roster agent |
| I-4 | Full test suite: every closed surface and every hook has a test; package coverage gates hold (meshsa 97%, jetson_yolo_gcs 96%); new security code targets 100% per-module, extending the documented `pacing` precedent — `netauth` itself lacked direct tests; fixed here | package `pyproject.toml` addopts | CI |
| I-5 | Scope freeze: no edit widens past M2 or touches the Initiative-C command emission path while its gate is unmet | `ROADMAP.md` commanding gate | `scope_freeze.py` PreToolUse hook |
| I-6 | Agents collaborate by default; the security-reviewer agent reviews every diff before PR | — | AGENTS.md directive + roster |

## Impact

- Affected specs: `m2-bind-safety`, `agent-governance` (new, this bundle);
  `docs/specs/m2-soak-fuzz.md` (authored)
- Affected code: `.claude/agents/**`, `.claude/hooks/**`,
  `tools/claude_hooks/**`, `tools/validate_workforce.py`, `.mcp.json`,
  `packages/meshsa/src/meshsa/netauth.py` (seam + no behavior change),
  `packages/meshsa/src/meshsa/transports/detection_ingest.py`,
  `packages/jetson_yolo_gcs/src/jetson_yolo_gcs/core/config.py` +
  `streaming/gstreamer.py` + `pipeline.py`, `flightctl/run_commander.py`,
  `packages/meshsa/tests/test_netauth.py`, `test_link_loss_soak.py`
- Affected behavior at runtime: surfaces #10 and #14 stop failing open; the
  commander's importable guard refuses an **empty** token on non-loopback bind
  (its `main()` already normalized `"" → None`, so the CLI path was safe; the
  API path was not); no other behavioral change. Read-only-by-default posture
  preserved.
