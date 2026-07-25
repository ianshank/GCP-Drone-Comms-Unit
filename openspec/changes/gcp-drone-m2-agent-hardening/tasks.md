# Tasks — gcp-drone-m2-agent-hardening

> Order binding. Each task: implement → tests green → ruff/mypy clean →
> coverage gate → commit. Checkboxes reflect the implementing PR.

## Phase 0 — Ground truth (no writes)
- [x] T-0.1 Verified the `AUDIT_M2_AUTH.md` inventory against current code
      (peer review, `docs/OPENSPEC_M2_BUNDLE_PEER_REVIEW.md`). Drift found and
      fixed in this PR: `NEXTSTEPS.md` stale no-heartbeat-gate claim; the
      commander's local `validate_bind` duplicate (D-3.3). Known remaining:
      stale `--cov-fail-under=90` in generated `egg-info/PKG-INFO` (build
      artifact, regenerates).
- [x] T-0.2 Confirmed `openspec/` absence and `docs/specs/` authority;
      bootstrap is additive (`docs/specs/` untouched except the authored
      `m2-soak-fuzz.md` + index row).

## Phase 1 — OpenSpec bootstrap + config (additive)
- [x] T-1.1 `openspec/` scaffold + `.claude/governance.yaml` + Pydantic loader
      (`extra="forbid"`); loader tests cover unknown-key/missing/invalid.
- [ ] T-1.2 `openspec` CLI in CI (`openspec validate --strict`). **Deferred**:
      the CLI is not installed in this repo/CI; adding a Node toolchain to CI
      is a maintainer decision.

## Phase 2 — Guardrails BEFORE agents touch code
- [x] T-2.1 `packages/meshsa/tests/test_netauth.py`: direct tests for
      `is_loopback` / `authorize` / `validate_bind` (incl. empty token) and
      the `TransportAuthPolicy` seam.
- [x] T-2.2 `bind_guard.py` (CI + CLI) + tests; repo scan clean (125 files,
      2 declared exceptions with rationales).
- [x] T-2.3 `scope_freeze.py` + tests (gate met/unmet, override logged,
      command-emission match, fail-open on malformed input);
      `session-start.sh` extended additively (fail-open count banner).
- [x] T-2.4 `security-reviewer` roster agent created first; review rules
      include the guard-predicate lesson from this change's own review.

## Phase 3 — Remaining subagents
- [x] T-3.1 `tools/validate_workforce.py`: roster lints (frontmatter schema,
      ≤60 lines, name=filename, uniqueness, `Relationship:` marker with
      existing-path check) + tests.
- [x] T-3.2 `bind-auditor`, `config-guardian`.
- [x] T-3.3 `openspec-author`, `test-engineer`, `charter-gate-keeper`.
- [x] T-3.4 `soak-engineer`. `validate_workforce` green on the real roster.

## Phase 4 — Close the named fail-open gaps
- [x] T-4.1 Surface #10 UDP ingest: `validate_bind` at construction + `token`
      option + fail-closed tests (direct + registry path + empty token) +
      non-loopback warning test.
- [x] T-4.2 Surface #14 GStreamer RTP: `StreamSettings.enabled=False` +
      default-off test + env opt-in test + single-WARNING activation test.
- [x] T-4.3 Commander unification: local predicate deleted; delegating adapter
      over `meshsa.netauth.validate_bind`; empty-token fail-closed test.
- [x] T-4.4 `TransportAuthPolicy` seam (+ `NetAuthPolicy` default, tests);
      **no** signing implementation (gated; audit gap stays recorded).

## Phase 5 — Resilience soak
- [x] T-5.1 `test_link_loss_soak.py` (interlock/pacer/backoff soaks + nightly
      fuzz) + `docs/specs/m2-soak-fuzz.md` authored, indexed. On-radio bench
      (§8) pending → `Validated`; evidence to land under `ops/`.

## Phase 6 — Command-gate integration test (verify, do not ship)
- [x] T-6.1 `tools/claude_hooks/tests/test_command_gate_integration.py`: real
      governance config has `c_gate_met=false`, the freeze globs cover
      `command/service.py` + `run_commander.py`, and the hook denies live
      writes to both. Bind-side: commander refuses non-loopback without a
      non-empty token (`test_run_commander.py`). Tests the gate; does not
      enable commanding.

## Phase 7 — MCP + docs
- [x] T-7.1 `.mcp.json` (GitHub only, secretless env reference). The
      read-only PR-list smoke runs where a GitHub MCP client is configured;
      this environment exercises the equivalent GitHub MCP tools for the PR
      workflow itself.
- [x] T-7.2 `AGENTS.md` collaboration directive + `.claude/agents/` pointer;
      `CLAUDE.md` pointer line; `NEXTSTEPS.md` stale-claim fix + audit-finding
      updates; `AUDIT_M2_AUTH.md` rows/gaps updated "this branch".

## Explicitly deferred (separate changes)
- Any Initiative-C commanding enablement (charter-gated on M2 completion)
- Transport-wide signing implementation (seam only, this change)
- `mavlink_source` bind guard (`udpin:` endpoint parsing differs from
  host/token; needs its own small design — tracked in NEXTSTEPS)
- M3/M4/M5, Scout/Initiative-D hardware paths
- Adoption of external research findings — none are currently cited in-repo;
  any future adoption requires a verifiable citation checked into `docs/` first
- Repo-wide Ruff `PL` enablement (maintainer decision; no-magic-numbers stays
  prose policy meanwhile)
- `openspec` CLI in CI (T-1.2)
