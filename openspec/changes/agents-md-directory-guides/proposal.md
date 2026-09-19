# OpenSpec Change: Per-Directory `AGENTS.md` Guides

- **change_id**: `agents-md-directory-guides`
- **project**: GCP-Drone-Comms-Unit (repository `ianshank/GCP-Drone-Comms-Unit`)
- **status**: proposed — plan only; no guide files land in the PR that carries
  this bundle
- **milestone**: M2 (Hardening & productization) — documentation/governance
  work; does **not** open M3/M4 and does **not** touch the Initiative-C gate
- **authoritative sources**: `AGENTS.md`, `CLAUDE.md`, `docs/CHARTER.md`,
  `docs/ROADMAP.md`, `CONTRIBUTING.md`, `docs/C4.md`
- **related bundles**: `openspec/changes/gcp-drone-m2-agent-hardening`
  (established the roster + `validate_workforce`),
  `openspec/changes/code-hygiene-modularity` (established `validate_skills`)
- **standards baseline**: researched 2026-09-19 — see `design.md` §D-0

## Why

Three facts define this change.

1. **The repo already committed to scoped `AGENTS.md`, then stopped at four.**
   The root `AGENTS.md` instructs every agent to "read the nearest scoped
   `AGENTS.md` in the folder you are editing", and `docs/specs/README.md`
   repeats it in the canonical reading order. Only `packages/meshsa`,
   `packages/jetson_yolo_gcs`, `ops`, and `hardware` have one. An agent
   editing `flightctl/`, `lib/`, `artifacts/`, `tools/`, `deliverables/`, or
   any subsystem under `src/meshsa/` follows that instruction and finds
   nothing, so it falls back to the 135-line root file — which cannot tell it
   that `lib/api-zod/src/generated/` is generated, that
   `artifacts/*/.replit-artifact/` is a deployment manifest, or that
   `packages/meshsa/src/meshsa/command/` is frozen by
   `.claude/governance.yaml`.

2. **Claude Code does not currently load any of them.** [Certain] Claude
   Code's default `claude-md-or-agents-md` instruction mode reads `AGENTS.md`
   *only* when no `CLAUDE.md` exists in the working directory or above it.
   This repo has a root `CLAUDE.md`, so every `AGENTS.md` in the tree — root
   and scoped alike — is read only if the model happens to act on the root
   `CLAUDE.md`'s prose pointer. The pointer is a markdown link, not an
   `@AGENTS.md` import, so nothing loads it mechanically. The repo's
   distinguishing asset is governance enforced in code; its agent
   documentation is currently enforced by hope.

3. **"One file per directory" is the wrong instinct, and the evidence says
   so.** 114 directories carry tracked files. Published measurement of
   machine-generated `AGENTS.md` files found they *reduced* task success in 5
   of 8 tested settings and added 2.45–3.92 extra steps per task, because
   generic instructions burn context that the actual work needs. The value is
   not in coverage; it is in each file carrying something the parent file
   cannot say. This change therefore proposes **tiered** coverage — 36 files,
   each with a line budget, a recorded reason for existing, and a mechanical
   check — rather than 114. `tasks.md` also lists the directories deliberately
   left uncovered, so "absent" is distinguishable from "forgotten".

## What Changes

- **A committed authoring contract** — a fixed section order, per-tier line
  budgets, a Mermaid policy, and a "no repo-wide rules in a scoped file" rule
  — shipped as `.agents/skills/agents-md-authoring/SKILL.md` so it is linted
  by the existing `tools/validate_skills.py` and discoverable the same way
  every other repeatable workflow in this repo is.
- **A tiered rollout** of `AGENTS.md` files across four tiers (root, domain
  root, subsystem, generated-code guard file), listed exhaustively in
  `tasks.md`. Every file states that folder's purpose, its key files, the
  rules that are true *only* there, the literal commands that work there, and
  which subagent/skill owns work in it.
- **Mermaid diagrams** in Tier 0/1 files (and Tier 2 where a flow is
  non-obvious), each carrying `accTitle:`/`accDescr:` and a prose summary, and
  each scoped to that folder's boundary rather than re-drawing `docs/C4.md`.
- **A `## Subagents` section in every guide**, naming the existing
  `.claude/agents/`, `.agents/skills/`, and `.github/agents/` entries that
  apply to that folder — delegation becomes discoverable from where the agent
  is working, not only from the root.
- **One new roster agent**, `docs-cartographer` (`.claude/agents/`), which
  owns authoring and refreshing the guide tree and its diagrams. Without an
  owner this rollout becomes the stale-documentation problem it is meant to
  fix.
- **A Claude Code loading bridge**: the root `CLAUDE.md`'s pointer becomes a
  real `@AGENTS.md` import, and each directory that gains an `AGENTS.md` gains
  a three-line `CLAUDE.md` that imports its sibling. Nested `CLAUDE.md` files
  load on demand when Claude reads a file in that subtree, so the tree costs
  nothing at session start and is loaded mechanically rather than by prose.
- **A mechanical checker**, `tools/validate_agents_docs.py` — the third
  sibling of `validate_workforce.py` and `validate_skills.py` — wired into
  `make -f tools/Makefile checkers`, `scripts/validate-pre-pr.sh`, and CI's
  `governance` job. It enforces the manifest, section order, line budgets,
  cited-path existence, Mermaid accessibility, subagent-reference validity,
  command validity, and the `CLAUDE.md`↔`AGENTS.md` pairing.

## What Does Not Change

- `docs/C4.md` and `docs/architecture/C4.md` remain the single home for
  system-level architecture. Guides link to them; they never re-draw them.
- `.agents/skills/` stays the home for *workflows*; `AGENTS.md` stays the home
  for *place*. A guide names a skill, it does not inline one.
- `docs/specs/` stays authoritative for initiative specs. This bundle is
  additive governance, consistent with the note in the root `AGENTS.md`.
- No source, transport, bind, or command-path file is touched. The
  Initiative-C freeze (`c_gate_met: false`) is untouched and unreferenced
  except as content to document.

## Impact

| Area | Effect |
| ---- | ------ |
| New files | 31 `AGENTS.md` (36 total, 5 exist), 35 `CLAUDE.md` stubs, 1 skill, 1 roster agent, 1 checker + its tests |
| Modified files | root `AGENTS.md`, root `CLAUDE.md`, 4 existing scoped `AGENTS.md`, `tools/Makefile`, `scripts/validate-pre-pr.sh`, `.github/workflows/ci.yml`, `.pre-commit-config.yaml`, `CONTRIBUTING.md`, `CHANGELOG.md` |
| Session-start context cost | +0 tokens. Only the root `AGENTS.md` loads at launch (via the import); scoped guides load on demand |
| CI | One added step in the existing `governance` job; no new job, no new matrix |
| Risk | Low. Documentation and one stdlib-only checker. The reversible failure mode is a red `governance` job, not a broken runtime |

## Open Questions for the Maintainer

1. **Tier 2 breadth.** `tasks.md` proposes 10 subsystem guides under
   `src/meshsa/`. `cv/` and `llm/` sit at the margin — each has a real
   invariant, but each is small enough that `packages/meshsa/AGENTS.md` could
   carry it. They are included as proposed; dropping them is a one-line
   manifest edit. Named in `design.md` §D-2 as a deliberate call, not an
   oversight.
2. **The `CLAUDE.md` stub tree.** 36 three-line files is the price of
   mechanical loading on Claude Code. `design.md` §D-6 records the two
   alternatives (symlinks, user-level `instructionFiles` setting) and why each
   loses. If the file count is unacceptable, the fallback is Tier 0/1 stubs
   only, accepting prose-only discovery below that.
