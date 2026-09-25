# OpenSpec Change: Agent Trap Documentation

- **change_id**: `agents-md-directory-guides`
- **project**: GCP-Drone-Comms-Unit (repository `ianshank/GCP-Drone-Comms-Unit`)
- **status**: proposed (rev.4) — rev.1–rev.3 are superseded and were substantially wrong
- **milestone**: M2 (Hardening & productization); does **not** open M3/M4 and does **not**
  touch the Initiative-C gate
- **authoritative sources**: `AGENTS.md`, `CLAUDE.md`, `.github/copilot-instructions.md`,
  `docs/CHARTER.md`, `docs/ROADMAP.md`, `CONTRIBUTING.md`
- **evidence register**: `docs/AGENTS_MD_EVIDENCE.md` (seven primary papers, each read in
  full; every claim carries its significance)
- **peer review**: `docs/OPENSPEC_AGENTS_MD_PEER_REVIEW.md` — four rounds. Round 3 was
  empirical; round 4 attacked the premise and **won**, cutting the change from 64 new
  files to 6
- **related bundles**: `openspec/changes/gcp-drone-m2-agent-hardening` (this bundle
  **amends** its "Agents Collaborate by Default" requirement),
  `openspec/changes/code-hygiene-modularity`

## Why

Three facts, in descending order of certainty.

1. **[Certain] Nothing in the guide tree loads today.** Claude Code's default
   `claude-md-or-agents-md` mode reads `AGENTS.md` *only* when no `CLAUDE.md` exists at or
   above the working directory. `CLAUDE.md` line 3 is a markdown link, not an `@AGENTS.md`
   import. So the root guide and all four scoped guides are read only if the model happens
   to go looking. **One character class change unlocks whatever value instruction files
   have here.** Everything else in this bundle is a bet by comparison.

2. **[Certain] The repo's agent docs carry wrong facts, and a wrong fact on a safety path
   is worse than a missing one.** Peer review found two live documents —
   `packages/jetson_yolo_gcs/AGENTS.md` and `.agents/skills/jetson-perception/SKILL.md` —
   both stating that the `LANDING_TARGET` publish "fails loud". It tolerates then
   escalates, against `publish_failure_tolerance` (default `3`). An agent asked to preserve
   the stated invariant would have deleted the tolerance window. **Both are corrected on
   this branch already**, ahead of any rollout, because the fix was two lines and the
   defect was live. Review also found that `docs/AUDIT_M2_AUTH.md`'s declared scope covers only
   `packages/meshsa` and `packages/jetson_yolo_gcs`, while the ROADMAP M2 invariant is
   repo-wide — and that at least three unaudited non-loopback unauthenticated surfaces sit
   in that gap (T-0.3).

3. **[Likely] The content worth writing is traps, and this repo has ~89 of them.** The one
   effect that survived measurement in the literature is a file carrying explicit cost and
   ordering warnings: blind full-suite test runs fell 3.67 → 1.67 per task, wall-clock ~24%
   (E-2). Repository overviews and structure maps are measurably inert where other
   documentation exists (E-1 §4.3), which is this repo. Traps are the deliverable.

## What changed from rev.3, and why

rev.3 proposed **35 `AGENTS.md` + 33 `CLAUDE.md` stubs = 64 new files, ~1,630 lines, a
14-check 600–900 LOC validator, and six phases.** An adversarial pass measured it against
this repository's own history and it did not survive:

| Finding | Measurement | Consequence |
| ------- | ----------- | ----------- |
| Payload density | ~116 lines of real traps inside ~1,630 lines of file | ~7% payload, 93% scaffolding |
| Nesting multiplier | 3.91 guides obligated per structural commit; 387 refresh obligations across 283 commits | The cost driver is nesting, not content |
| Observed compliance | The 5 guided directories accrued 170 refresh obligations in 109 days; the guides took 41 commits — **24%** | Three-quarters of obligations already go unmet at 6 files |
| Growth, measured in-repo | Root `AGENTS.md` 96 → 135 lines (+41%) in 73 days, **+16 lines/month**, monotone | 7–8 of 35 guides breach budget within 12 months; the root breaches in month 1–2 |
| Skill Leakage, by the bundle's own cited definition | ~55–60 of the 89 traps are procedure (regenerate-with, run-this-command, coverage floors) | rev.3's Scope section forbade exactly what its manifest did ~60 times |
| Standing repo policy | `.github/copilot-instructions.md:9` — *"create or update a skill under `.agents/skills` instead of expanding this file"* | rev.3 inverted a written policy without citing it |

A budget that fires converts a documentation line count into a **merge gate**: check 3
exits non-zero → `make checkers` red → CI `governance` red → every PR blocked until someone
deletes prose unrelated to their change. On the measured growth rate that happens inside
60 days.

rev.4 keeps the content and throws away the container.

## What Changes

**Step 0 — ship independently of the rest.** Certain, small, and should not wait behind a
rollout.

- `CLAUDE.md`: `[AGENTS.md](AGENTS.md)` → `@AGENTS.md`. That is the whole of fact #1.
- The two `LANDING_TARGET` corrections. **Already landed on this branch.**
- Widen `docs/AUDIT_M2_AUTH.md`'s scope beyond `packages/` and add the missing rows.

**Step 1 — `## Traps` in the five existing guides. No new instruction files.** All ~89
trap facts fit: 36 into `packages/meshsa/AGENTS.md`, 8 into
`packages/jetson_yolo_gcs/AGENTS.md`, 3 into `ops`, 2 into `hardware`, 40 into the root —
which lands at ~170 lines with zero new files. Two content rules survive from rev.3,
each backed by a specific finding:

- **`— why:` on every rule.** Deletion hazard falls with instruction age because the reason
  decays faster than the rule; recording it removed 99.3% of excess size (E-3). It is the
  only remedy in the literature that is independent of file count.
- **`— control:` or `— advisory` on every security rule.** Only ~4.4% of security rules in
  public instruction files have a matching control, and nothing marks which (E-6). This
  repo *has* the controls.

**Step 2 — six `.claude/rules/*.md` with `paths:` frontmatter.** Path-scoped rules load on
demand when a matching file is touched. This is the honest answer to the one case five
files cannot serve: a guard warning must fire *when an agent opens the generated file*, and
rev.3 could not deliver it — `clean: true` deletes a guide placed where it would fire, so
rev.3 relocated it to the parent, sacrificing the firing property that its own spec called
the guard file's entire purpose. A `paths:` rule matching `lib/*/src/generated/**` fires on
the file and cannot be deleted by codegen, because it does not live there.

| Rule file | `paths:` | Traps |
| --------- | -------- | ----- |
| `meshsa-core.md` | `packages/meshsa/src/meshsa/**` | 30 |
| `meshsa-tests.md` | `packages/meshsa/tests/**` | 4 |
| `perception.md` | `packages/jetson_yolo_gcs/**` | 8 |
| `generated-code.md` | `lib/*/src/generated/**`, `artifacts/mockup-sandbox/src/.generated/**`, `.../components/ui/**`, `archive/**` | 7 |
| `ts-workspace.md` | `lib/**`, `artifacts/**` | 10 |
| `governance.md` | `tools/**`, `.claude/**`, `.github/**`, `scripts/**` | 13 |

**Step 3 — procedure-shaped content goes to skills, per the repo's own standing policy.**
Most already have a home: coverage floors in `pre-pr-validator`, the Hypothesis profile in
`meshsa-test-conventions`, snapshot regeneration in `meshsa-schema-version-bump`,
import-time registration in `meshsa-add-transport`, `M2R_BIND` and `run_commander` in
`meshsa-commanding-safety`, `defaults.py` in `config-literal-sweep`, `§` numbering and the
checkbox-parser trap in `spec-driven-change`. At most three new skills where none fits.

**Step 4 — a four-check validator, not fourteen.** Keep: manifest ↔ `git ls-files`
agreement, cited-path existence, control-character hygiene, `## Traps` present. Drop the ten checks
that existed only to police the 69-file tree's own structure — canonical section order,
line budgets, breadcrumb-nearest-ancestor, Mermaid fence mechanics, subagent-name
resolution, dual-Makefile disambiguation, stub pairing, negation detection,
action-directive grammar, reverse coverage. Delete the tree and they delete themselves.
Check 5 carries the five corrections round 3 measured (9 false positives → 1).

Mermaid survives, in the five `AGENTS.md`, where a diagram encodes a constraint the code
cannot show — bring-up ordering, codegen direction, a governance gate — with
`accTitle`/`accDescr` and a prose summary. Structure diagrams stay in `docs/`.

## Invariants (binding on every task)

| # | Invariant | Source | Enforcement |
| - | --------- | ------ | ----------- |
| I-1 | A guide or rule may add a constraint; it may never relax one the root sets | `docs/ROADMAP.md` M2 invariant; CHARTER §4 | Review. Mechanical detection was specified twice, measured twice, and dropped — peer review R-2 |
| I-2 | `governance.c_gate_met` stays `false`; no glob list is edited, **and no documentation data enters `governance.yaml`** | `.claude/governance.yaml`; CHARTER §6 | rev.3 argued the manifest must stay out of that file because its loader fails open, then added an exceptions block to it six tasks later. rev.4 puts nothing there |
| I-3 | No instruction file is written into a frozen path | design §D-6 (verified against `match_globs`) | `scope_freeze.py` denies it |
| I-4 | No rule restates a security constraint without naming its control or marking it advisory | E-6 | Checker + `security-reviewer` before PR |
| I-5 | Every external claim cites `docs/AGENTS_MD_EVIDENCE.md` with its significance | `docs/OPENSPEC_M2_BUNDLE_PEER_REVIEW.md` F-1 | Review |
| I-6 | New Python in `tools/` passes ruff, ruff format, mypy and pytest | CHARTER §4 Invariant 6 | Per-task gate in `tasks.md` |

## Scope — what this change is NOT

- **Not a per-directory guide tree.** That was rev.1–rev.3 and it is withdrawn. The
  reversal is recorded rather than quietly dropped, because the trap register it produced
  is the best artifact in the bundle and is fully reused.
- **Not a replacement for `.agents/skills/`.** The opposite: it returns procedure to them,
  which `.github/copilot-instructions.md` already required.
- **Not a claim that instruction files improve task success.** They do not, on the evidence
  (E-1, E-2). The claims here are traps avoided, a loading bug fixed, and two wrong safety
  statements corrected.
- **Not security-neutral.** `.claude/rules/` files are the same trusted, uninspected entry
  point as an `AGENTS.md`. rev.4 wins on **count** — 6 new instruction files instead of 64
  — not per file.

## Impact

| Area | rev.3 | rev.4 |
| ---- | ----- | ----- |
| New instruction files | 64 | **6** |
| Total instruction files | 69 | **11** |
| New prose lines | ~1,630 | **~330** |
| New Python | 600–900 LOC + tests | **~120 LOC + tests** |
| Checks | 14 | **4** |
| Phases / stop points | 6 / 2 | **1 + a ship-now step** |
| Refresh obligations per year | ~1,300 | **~470** |
| Budget breaches in 12 months | 7–8 | 1 (the root, already breaching) |
| Traps captured | 89 | **~85** |

## Open calls for the maintainer

1. **`.claude/rules/` is Claude-only.** Codex, Copilot and Cursor read `AGENTS.md`, not
   `.claude/rules/`, and `.github/copilot-instructions.md` names `AGENTS.md` canonical. The
   hybrid keeps the five `AGENTS.md` as the portable layer and uses rules only for
   path-scoped ambient traps. If portability of that content matters more than the firing
   property, those six rules become prose in the five guides and `generated-code.md`'s
   fire-on-open behaviour is lost.
2. **The root lands at ~170 lines and grows +16/month, measured.** Either accept that the
   root is the one file allowed to be large and drop the budget check, or schedule a
   deliberate split later. rev.4 proposes the former: a budget that blocks merges is worse
   than a long file.
3. **Step 0 should not wait for the rest.** Three small changes, two already landed. Say if
   you want them split into their own PR.
