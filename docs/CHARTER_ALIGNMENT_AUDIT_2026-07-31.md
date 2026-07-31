# Charter Alignment Audit — 2026-07-31

> First run of [CHARTER_ALIGNMENT_AUDIT_PLAN.md](CHARTER_ALIGNMENT_AUDIT_PLAN.md)'s Phase A–E
> method, requested as a full repo-wide gap analysis / code-hygiene / tech-debt pass. Executed as
> five parallel read-only recon streams (meshsa quality gates, jetson_yolo_gcs quality gates, a
> repo-wide magic-number sweep, a real Phase D bind/auth re-derivation, and a doc/infra staleness
> sweep), followed by two isolated-worktree fix streams for the findings judged safe to fix
> directly. Reviewed against the tree at branch `claude/project-charter-alignment-3ci0se`,
> commits `2b737cd`…`492abed`. This report does not amend `CHARTER.md`/`ROADMAP.md` and did not
> touch `.claude/governance.yaml`/`c_gate_met`, per the plan's own non-goals.

## Summary

| Phase | Verdict | Reason |
| --- | --- | --- |
| A — Scope conformance | **Aligned** | Not run as a dedicated pass this time; corroborated incidentally by the other four streams: `meshsa/federation/**`/`meshsa/storeforward/**` confirmed absent (only as path-string test fixtures), no general-purpose message-broker surface found, the four in-scope directories account for everything the recon agents read across ~150 file touches. |
| B — Carve-out compliance | **Partially aligned — 1 item needs a maintainer decision** | Initiative-C: `c_gate_met` still `false`, `COMMAND_INT` + bounded-retry `ACK` confirmed implemented — but see Finding 1 below (frozen-path magic numbers, not fixed). On-board perception and on-board tracker: confirmed compliant (config-driven defaults, no `meshsa` runtime dependency). ArmGuard and Scout carve-outs were not re-verified this pass (last verified in the prior peer-review round, not re-run here). |
| C — Invariant conformance | **Aligned, with fixes applied** | Invariant 5 (no magic numbers): 3 real gaps found and fixed in `jetson_yolo_gcs`; 2 found in `meshsa/command/**` and flagged only (governance-frozen, see Finding 1); 1 found and flagged (`llm/agent.py` config fragmentation); 2 confirmed as already-tracked debt (T-3/T-3.5), not re-touched. Invariant 6 (gates green): **meshsa 1118 passed / 6 skipped / 99.31% cov; jetson_yolo_gcs 222 passed / 99.35% cov** — both green after fixes. Invariant 7 (no secrets): clean. Invariants 1–4 were not directly re-tested this pass. |
| D — Bind/auth posture | **Aligned, corrected** | True fail-open surface count re-derived: **3**, of which only **1** (`TakMulticastTransport`) is an actual `bind_guard`-scoped gap, and it's a declared, still-valid governance exception. `AUDIT_M2_AUTH.md` corrected in place. No new bind surface found since 2026-07-08; all 3 `bind_guard.exceptions` re-verified valid. |
| E — Roadmap/backlog consistency | **Aligned, with fixes applied** | `IMPLEMENTATION_PLAN.md` was stale (957/174 tests cited vs. 1114/205 actual at sweep time) — corrected with a dated note. `NEXTSTEPS.md`, `openspec/changes/*`, and `docs/specs/` status column confirmed accurate. |

Plus supplementary findings outside the five phases, surfaced by the same sweeps and fixed in the
same pass: `docs/ARCHITECTURE.md` had an unrelated stale test-count line; `scripts/validate-pre-pr.sh`
undersold its own step count and — more materially — never actually ran `jetson_yolo_gcs`'s test
suite despite lint/type-checking it; `README.md` never mentioned the Python drone-comms side of the
repo; `.gitignore` had no rule for the Claude Code harness's worktree directories and a stale
blanket-ignore that contradicted `.agents/skills/`'s real tracked status. All fixed — see Findings
8–11.

## Findings

**1 — `[Flagged, not fixed — governance-frozen]`** Two magic-number gaps live inside the
Initiative-C command path, which `.claude/governance.yaml`'s `scope_freeze` hook denies writes to
while `c_gate_met` is `false`: `command/mavlink_pump.py`'s `read_timeout_s: float = 0.5` has no
`CommanderConfig` field and is unconfigured in production (`flightctl/run_commander.py::build_service`
constructs it without an override); `command/health.py`'s `HeartbeatHealth` bare default
(`max_age_s: float = 3.0`) silently diverges from the value production actually uses
(`CommanderSettings.arm_report_max_age_s`, default `2.0`) — **the correct value between 3.0 and
2.0 is itself the open question**, so this is not a mechanical fix. CHARTER §4 Invariant 5.
Recommended next step: maintainer decision per CHARTER §6 on which default is correct, then a
change to the frozen path once decided — not something this pass can or should resolve.

**2 — `[Fixed]`** `jetson_yolo_gcs/utils/jetson.py`'s subprocess timeout and tegrastats poll
interval had no config home at all. Added `JetsonSettings` (`JETSON_*` env prefix), same defaults.
CHARTER §4 Invariant 5. Commit `c803fb5` (merged `492abed`).

**3 — `[Fixed]`** `jetson_yolo_gcs/utils/fps.py`'s `FpsCounter` window and `pipeline.py`'s
`idle_poll_s` were constructed from bare class defaults in production instead of the
settings-derivation pattern the same file already uses for its sibling parameters. Added
`PipelineSettings.fps_window`, wired both through explicitly. Same defaults, no behavior change.
CHARTER §4 Invariant 5. Commit `c803fb5` (merged `492abed`).

**4 — `[Flagged, not fixed]`** `llm/agent.py` resolves `MESHSA_LLM_MAX_TOKENS`/
`MESHSA_LLM_MAX_ITERATIONS` via a standalone `os.environ.get(...)` inside `build_agent()`, a second
env-resolution path parallel to (not integrated with) `llm/server.py`'s `ServerConfig`. Not a bare
magic number (both are correctly `MESHSA_`-prefixed and overridable) but a config-home
fragmentation. Moderate-risk to fix (touches agent-construction control flow); left for a follow-up
rather than folded into this pass. CHARTER §4 Invariant 5.

**5 — `[Confirmed already-tracked, not re-touched]`** `transports/tak.py`/`transports/detection_ingest.py`
duplicate `meshsa/defaults.py`'s port table as local literals instead of importing it, and the four
aiohttp server factories (`health.py`, `scout/station/app.py`, `llm/server.py`, `ui/app.py`, plus
`flightctl/run_commander.py`) still hand-roll duplicate `web.Application()` + bearer-guard
boilerplate. Both are explicitly disclosed, sequenced future work — `defaults.py`'s own docstring
(T-3.5) and `NEXTSTEPS.md`'s code-hygiene-modularity T-3 (currently unchecked). Re-confirmed
current and located concretely; not re-implemented here to avoid preempting an already-sequenced,
separately-owned refactor (T-3's own tracking already caught one concrete drift: only `health.py`
sends the RFC 7235 `WWW-Authenticate` challenge header on 401, the other four don't).

**6 — `[Fixed]`** `meshsa/netauth.py::validate_bind` — the single canonical fail-closed primitive
used by ~9 call sites — logged nothing before raising on a bind rejection; the diagnostic text
existed only in the exception message. Added one centralized `structlog` warning, benefiting every
call site without duplicating logging into each one. `meshsa/ui/app.py`'s chat handler was the one
exception-swallow in that file with no logging at all (its six siblings all log); brought in line.
CHARTER §4 (logging/debuggability, requested explicitly this pass). Commit `8c3cab0` (merged
`492abed`).

**7 — `[Fixed]`** `meshsa/transports/tak.py::_require_file`'s "not a regular file" branch had zero
test coverage (distinct from its sibling permission-check branch, which has a test that
self-skips only because this sandbox runs as root). Added a real test pointing `_require_file` at
a directory. `meshsa/scout/__main__.py`'s 3-line entry shim was genuinely untested (0% coverage,
no test imports it); added the same `# pragma: no cover` convention used at every other process
entry point in the package, rather than writing a low-value test for two import statements. CHARTER
§4 Invariant 6 (gates green; only hardware/process-entry glue is pragma'd). Commit `8c3cab0`
(merged `492abed`).

**8 — `[Fixed]`** `docs/AUDIT_M2_AUTH.md` rows #10/#11 and two Gap-summary items described the
pre-`fab3ab1` (2026-07-29) state: `mavlink_source` as fail-open (it's now fail-closed via
`validate_bind`) and `detection_ingest`'s port as `8099` (moved to `8097`). Corrected in place;
re-derived and stated the true fail-open count (3, only 1 `bind_guard`-scoped); resolved 2 stale
backlog items. `docs/IMPLEMENTATION_PLAN.md` and `docs/ARCHITECTURE.md` cited a 2026-07-08 test
snapshot (957/174 tests) against a then-current 1114/205 (now 1118/222 post-fix) — both updated
with fresh figures and an explicit caveat that the numbers are snapshots, since this exact spot has
now gone stale twice. Commit `4b10b83`.

**9 — `[Fixed]`** `scripts/validate-pre-pr.sh`'s header comment described 6 steps; it runs 10, and
undersold the syntax-check step's real scope (`packages/`, `flightctl/`, `tools/`, `deliverables/`,
not `deliverables/` alone). More materially: the script lint/type-checks `jetson_yolo_gcs` but never
actually ran its test suite — the "full pre-PR gate" silently covered only one of the two packages'
tests. Added `step_py_test_jetson`, conditional on the directory existing (matching the pattern
`step_py_typecheck` already used). Commit `4b10b83`.

**10 — `[Fixed]`** Root `README.md` (scoped to the TS validation workspace) never mentioned the
Python drone-comms framework — `meshsa`, `jetson_yolo_gcs`, `flightctl/`, `hardware/`, `ops/` — that
is most of this repository. Added a short, additive pointer to `docs/CHARTER.md`, `docs/ROADMAP.md`,
and `packages/meshsa/README.md`; did not restructure existing content. Commit `4b10b83`.

**11 — `[Fixed]`** `.gitignore` had no rule for `.claude/worktrees/` (the Claude Code harness's
isolated-worktree directories for background subagents — this pass's own fix streams created two),
which tripped the repo's stop-hook untracked-files check. Added a narrowly-scoped rule (not a
blanket `.claude/` ignore, since `.claude/agents/` and `.claude/governance.yaml` are real tracked
content). While there, found and fixed a related pre-existing inconsistency: the blanket `.agents/`
ignore rule (labeled Replit internal state) contradicted `.agents/skills/`'s actual status as real,
tracked, load-bearing `AGENTS.md` playbooks — they stay tracked today only because they predate the
ignore rule; a *new* file added under `skills/` would have been silently invisible to `git status`.
Added negation patterns rather than removing the blanket rule outright, since other `.agents/`
content may be intentionally ignored for reasons this pass didn't investigate. Commit `93cf395`.

**12 — `[Fixed]`** Two of three CodeRabbit review findings on this PR's earlier commits were real
and still unfixed: `NEXTSTEPS.md` still said "six carve-outs" (the prior peer-review pass only
corrected `CHARTER_ALIGNMENT_AUDIT_PLAN.md`'s occurrences, missing this one); Phase A's grep
exclusion paths lacked the `packages/*/src/*` prefix used everywhere else in the same doc, so they
would not have matched a repo-root scan. Fixed both; verified the third finding (a citation) was
already correct, replied with evidence, and CodeRabbit withdrew it after independently re-checking.
Commit `7ac011e`.

## What was not run this pass

Phase A (dedicated scan), the ArmGuard and Scout carve-out rows of Phase B, and CHARTER §4
Invariants 1–4 were not directly re-verified — they were last checked in this session's earlier
peer-review round or not at all this session. A future full A–E run should cover these explicitly
rather than relying on incidental corroboration from a differently-scoped sweep.

## Verification

`ruff check .`, `ruff format --check .`, `python -m mypy src`, and the full `python -m pytest` all
green in both `packages/meshsa` (1118 passed, 6 skipped, 99.31% cov, floor 97%) and
`packages/jetson_yolo_gcs` (222 passed, 99.35% cov, floor 96%), run from each package directory
after merging both fix worktrees back into this branch.
