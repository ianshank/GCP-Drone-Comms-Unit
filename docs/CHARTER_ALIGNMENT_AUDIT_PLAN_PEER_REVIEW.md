# Peer Review — `CHARTER_ALIGNMENT_AUDIT_PLAN.md`

<!-- markdownlint-disable MD013 -->

> Reviewed 2026-07-31 against the working tree at `2b737cd` on
> `claude/project-charter-alignment-3ci0se` (PR #35). Ran in **two rounds**: an initial read-only
> fact-check of every concrete claim in the plan, then an adversarial round that tried to *refute*
> round 1's findings (all four survived; one got stronger) and independently hunted for anything
> missed. Every finding below was checked against actual files, git history, or live grep/test
> output — not asserted from memory. The correction is applied directly to
> `CHARTER_ALIGNMENT_AUDIT_PLAN.md` in the same commit that adds this review.

## Verdict

Of the specific counts this document states as fact, most were wrong. "5 fail-open surfaces,"
"six ratified carve-outs," and "five [other] subagents" were each independently checked and each
was wrong (F-1/F-3, F-7, F-8) — a reliability problem with self-asserted numbers, not one typo.
Beyond that: a Phase B carve-out row omits the one config seam CHARTER names by name (F-2), a
Phase D staleness check is written as a future hypothetical when the condition is already true
today and the underlying audit doc's *content*, not just its date header, is now functionally
wrong (F-3), the document contradicts its own citation-style rule in one place (F-5), an
IMPLEMENTATION_PLAN.md-shaped blind spot in Phase E/Reading order is already live (F-6), and the
Owner framing throughout implies tool-enforced subagent scoping that doesn't exist (F-4). The
phase structure (A–E) itself, and the majority of Phase B/C's concrete claims, are sound.

## Findings

**F-1 + F-3 `[Certain]`** — Ground truth section states "5 fail-open surfaces" as flat fact
(`CHARTER_ALIGNMENT_AUDIT_PLAN.md`, Ground truth). `AUDIT_M2_AUTH.md`'s surface table has only 4
rows whose "Fail-closed?" column says "fails open": #1 `TakTcpTransport`, #2
`TakMulticastTransport`, #4 `MeshtasticTransport`, #11 `MavlinkSourceTransport`. The 5th
`grep -ci 'fails open'` hit (the startup hook's method) is `AUDIT_M2_AUTH.md`'s Gap Summary
verbatim-echoing #11's status ("`mavlink_source` still has no guard and fails open on override") —
a double-count, not a 5th surface. **But the "corrected" 4 is not safe to assert either**: commit
`fab3ab1` (2026-07-29, "feat(test-plan): add comprehensive local test plan, security bind guards,
and cross-platform quality gate fixes") added a `validate_bind` fail-closed guard to
`MavlinkSourceTransport.__init__` (`transports/mavlink_source.py`) and moved
`DetectionIngestTransport`'s default port 8099→8097 — but `AUDIT_M2_AUTH.md`'s surface #11 row,
its Gap Summary bullet, and its backlog item #1 ("Fail-closed bind guard for `mavlink_source` on a
non-loopback `endpoint`") all still assert the pre-`fab3ab1` state. The audit doc's own content is
functionally stale, not just its `Date: 2026-07-08` header. Fix: the plan must not assert 5, 4, or
any other number as ground truth — it must name this drift and treat Phase D's re-derivation as
already-overdue work.

**F-7 `[Certain]`** — The plan says "six ratified carve-outs" three times (Why this plan exists;
Ground truth; Phase A point 1) but only ever lists five dates (2026-06-12, 2026-06-16, 2026-06-20,
2026-07-05, 2026-07-16). `CHARTER.md` contains exactly five
`> **Carve-out (deliberate amendment — ratified...)` blocks, at those same five dates (confirmed:
lines 36, 48, 77, 101, 120) — no sixth exists anywhere in the file. Fix: "six" → "five" in all
three spots.

**F-8 `[Certain]`** — Phase B's owner line says "general sweep for the other four (none of the
other five subagents have standing scope...)." `.claude/agents/` contains 7 files: `bind-auditor`,
`charter-gate-keeper`, `config-guardian`, `openspec-author`, `security-reviewer`, `soak-engineer`,
`test-engineer`. Excluding `charter-gate-keeper` (assigned separately to the Initiative-C row)
leaves six, not five. Fix: "five subagents" → "six subagents."

**F-2 `[Certain]`** — Phase B's Scout carve-out row cites `scout/export_mission.py`, `scout/cli.py`,
`scout/pipeline.py` for "Where to look," omitting `ScoutConfig` entirely. `CHARTER.md:114` names
it explicitly as a required seam: "Added behind `Protocol`/registry/config seams (`meshsa.scout`,
`ScoutConfig`, `MESHSA_SCOUT_*`)." `ScoutConfig` is the only class of that name in the repo,
defined at `packages/meshsa/src/meshsa/config.py:188` — in the shared framework config module,
not under `scout/` at all (searched `scout/protocols.py`, `scout/schemas.py`, and every other
`scout/*.py` file; no competing definition exists). Fix: add the `config.py` citation to the
Scout row, and note every operational value is a `ScoutConfig` field.

**F-6 `[Certain]`** — `AGENTS.md:9-12`'s canonical reading order is `CHARTER → ROADMAP → nearest
scoped AGENTS.md → NEXTSTEPS → IMPLEMENTATION_PLAN.md → LOCAL_TESTING_PLAN.md → the relevant
spec`. The plan's own Reading order line skips `IMPLEMENTATION_PLAN.md` entirely, and Phase E's
three checklist items (NEXTSTEPS↔ROADMAP mapping, `openspec/changes/*` scope, `docs/specs/`
status column) never touch it either. `IMPLEMENTATION_PLAN.md` makes concrete, checkable claims —
test counts and coverage percentages as of a "2026-07-08 reconciliation" note (`meshsa` 957
passed/99.16% cov, `jetson_yolo_gcs` 174/99.34% cov) — that are exactly the kind of thing that
drifts, the same failure class as F-1/F-3's `AUDIT_M2_AUTH.md` finding. A live spot-check during
this review found materially higher current counts (~1120 `meshsa` tests, ~205
`jetson_yolo_gcs` tests) — the doc is already stale again, right now, not hypothetically. Fix: add
`IMPLEMENTATION_PLAN.md` to the Reading order chain and add a 4th Phase E checklist item to verify
its dated claims against a live run.

**F-5 `[Certain]`** — The Deliverable section mandates future audit reports cite code as
"`module.py::symbol`, never a bare line number per the `charter-gate-keeper` citation convention" —
but Phase B's On-board perception row cites
`packages/jetson_yolo_gcs/src/jetson_yolo_gcs/core/config.py:88`, a bare line number, inside the
same document. A full-file scan found this is the only such occurrence — isolated, not
widespread (the `TrackerSettings` row in the same table already uses symbol style with no line
number). Fix: change the citation to symbol style, matching the `TrackerSettings` row and the
document's own stated rule, rather than relaxing the rule.

**F-4 `[Certain]`** — The Method preamble and the Phase B/D Owner lines say a subagent "is scoped
to" a phase or has "standing scope over" a directory. Checked all four relevant agents'
`.claude/agents/*.md` frontmatter (`bind-auditor`, `config-guardian`, `charter-gate-keeper`,
`security-reviewer`): every `tools:` grant (e.g. `Read, Grep, Glob, Bash(rg *)`) is repo-wide with
no path restriction. Also checked `tools/claude_hooks/` (`scope_freeze.py`, `bind_guard.py`,
`governance.py`) for any hidden per-agent path-scoping mechanism — none exists;
`scope_freeze.py` is a repo-global `PreToolUse` hook that gates only `Write`/`Edit` against
`command_emission_globs`/`scope_widening_globs` and has zero agent-name awareness. The only real
boundary is each agent's `description:` trigger text — a convention, not an enforced permission.
Fix: reword "is scoped to"/"standing scope over" to state assignment follows trigger-text
convention, not tool-enforced restriction.

## Considered, not actioned

- **Self-re-verification cadence.** The plan's growing carve-out list (five ratified amendments in
  under two months) might argue for a note about re-verifying the plan's own Ground Truth section
  periodically. Not actioned: the existing Cadence section already frames a full A–E pass as a
  maintainer-triggered periodic sweep, which covers this.
- **"General sweep" as a vague owner label.** Could be replaced with something more formal.
  Not actioned: it's already glossed concretely per-phase ("Explore/general-purpose agent" in
  Phase A; "none of the other ... subagents have standing scope over ..." in Phase B); renaming it
  is a stylistic redesign outside this review's mandate.
- **Fixing `AUDIT_M2_AUTH.md`'s stale surface #11 row directly in this PR.** F-1/F-3 found real
  drift in that file's content, not just its header. Not actioned here: correcting
  `AUDIT_M2_AUTH.md` itself is exactly the *Phase D* re-run's job, per the plan's own "Explicit
  non-goals" section (it does not amend the audit docs it cites). This PR only fixes what the
  *plan* claims about that file.

## What survived review unchanged

Phase C's seven-invariant table, including the now-confirmed `Protocol`-based DI claim
(`Transport`/`Codec`/`Clock`/`IdFactory` are all `class X(Protocol)` in
`packages/meshsa/src/meshsa/protocols.py`) and the on-board tracker's "no runtime dependency on
`meshsa`" claim (verified against `packages/jetson_yolo_gcs/pyproject.toml`); the Initiative-C
row's "`COMMAND_INT` + bounded-retry `ACK`" claim (verified implemented in
`command/lifecycle.py`, `command/commands.py`, `command/mavlink_link.py`); every `.claude/governance.yaml`
field name and value quoted in Ground truth (`c_gate_met`, `scope_widening_globs`,
`command_emission_globs`); the claim that `meshsa/federation/**` and `meshsa/storeforward/**`
don't exist as real modules (only as path-string test fixtures under
`tools/claude_hooks/tests/`); the five (corrected) carve-out dates and their CHARTER §3
cross-references; the Phase A–E structure itself; and the Deliverable/Cadence/Explicit non-goals
sections apart from the F-1/F-3 wording fix.
