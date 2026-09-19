# OpenSpec Change: Per-Directory `AGENTS.md` Guides

- **change_id**: `agents-md-directory-guides`
- **project**: GCP-Drone-Comms-Unit (repository `ianshank/GCP-Drone-Comms-Unit`)
- **status**: proposed (rev.2) — plan only; no guide files land in the PR that carries
  this bundle
- **milestone**: M2 (Hardening & productization) — documentation/governance work; does
  **not** open M3/M4 and does **not** touch the Initiative-C gate
- **authoritative sources**: `AGENTS.md`, `CLAUDE.md`, `docs/CHARTER.md`,
  `docs/ROADMAP.md`, `CONTRIBUTING.md`, `docs/C4.md`
- **evidence register**: `docs/AGENTS_MD_EVIDENCE.md` (seven primary papers, each read
  in full; every claim carries its significance)
- **peer review**: `docs/OPENSPEC_AGENTS_MD_PEER_REVIEW.md` — rev.1 was corrected against
  the tree and against the primary literature before implementation. Ten findings, five
  `[Certain]`; three inverted a rev.1 design decision
- **related bundles**: `openspec/changes/gcp-drone-m2-agent-hardening` (established the
  roster + `validate_workforce`; this bundle **amends** its "Agents Collaborate by
  Default" requirement), `openspec/changes/code-hygiene-modularity` (established
  `validate_skills`)

## Why

Four facts define this change. The first two are about this repository; the last two are
why rev.1 was wrong about what to build.

1. **The repo committed to scoped `AGENTS.md`, then stopped at four.** The root
   `AGENTS.md` tells every agent to "read the nearest scoped `AGENTS.md` in the folder you
   are editing", and `docs/specs/README.md` repeats it in the canonical reading order.
   Only `packages/meshsa`, `packages/jetson_yolo_gcs`, `ops`, and `hardware` have one. An
   agent editing `flightctl/`, `lib/`, `artifacts/`, `tools/`, or any subsystem under
   `src/meshsa/` follows that instruction and finds nothing.

2. **Claude Code does not currently load any of them.** [Certain] Claude Code's default
   `claude-md-or-agents-md` mode reads `AGENTS.md` *only* when no `CLAUDE.md` exists in
   the working directory or above it. This repo has a root `CLAUDE.md` whose pointer is a
   markdown link, not an `@AGENTS.md` import. So every guide in the tree — root and
   scoped alike — is read only if the model happens to go looking.

3. **The content type rev.1 planned is the content type the evidence finds inert.**
   Repository overviews, structure maps and file inventories do not measurably help
   (E-1 §4.3: *"Context files do not provide effective overviews"*), **except** in
   repositories that have no other documentation (E-1 Appendix B) — the opposite of this
   one, which has `docs/C4.md`, `docs/ARCHITECTURE.md`, `docs/specs/` and a
   `CONTRIBUTING.md` layout block. The one effect that survived measurement is narrow and
   specific: a file carrying explicit **cost and ordering warnings** cut blind full-suite
   test runs from 3.67 to 1.67 per task and wall-clock time by ~24% (E-2). This
   repository is full of exactly such traps — a single-file pytest run still fails
   `--cov-fail-under=97`; `lib/*/dist/` must be built before `pnpm -r run typecheck`;
   `mypy flightctl/ tools/` must stay one invocation; mavp2p `udpc` consumers must bind
   first; `.gitignore` must say `.agents/*`, never `.agents/`. **Traps are the
   deliverable. Overviews are not.**

4. **A guide tree is a security surface, and 35 of them is a big one.** [Certain]
   Instruction files are the highest-privilege prompt-injection entry point measured:
   the harness loads them as trusted system context *without checking what they contain*,
   with reachability 1 by construction, and the published threat model is a pull-request
   contributor (E-5). This repository ships `bind_guard`, `literal_guard` and a
   scope-freeze hook precisely because it does not trust prose. rev.1 rated this change
   "Low risk — documentation only". It is not, and rev.2 treats the tree as a declared
   surface with its own controls.

**No controlled study has evaluated nested per-directory context files.** E-1, E-2 and
E-4 all restrict to single-root configurations by design; E-2 explicitly excludes any
repository with a "competing instruction stack". This change is therefore a
**risk-managed bet, not an evidence-backed design**, and is scoped, budgeted and
instrumented accordingly. 35 files, not the 117 directories that carry tracked files.

## What Changes

- **An authoring contract** — fixed section order, per-tier line budgets, a mandatory
  `## Traps` section, a one-line rationale on every rule, and a control tag on every
  security-relevant rule — shipped as `.agents/skills/agents-md-authoring/SKILL.md` so it
  is linted by `tools/validate_skills.py` and discoverable like every other repeatable
  workflow here.
- **A tiered rollout** of 35 guides across four tiers, listed exhaustively in `tasks.md`
  with the trap that earns each one. Directories deliberately left uncovered are listed
  too.
- **Rationale on every rule.** Agentic context files grow +226% over their lifetime at
  +4.9 net instructions per commit, and deletion hazard *falls* with age because the
  reason an instruction exists decays faster than the instruction (E-3). Recording that
  reason removed 99.3% of excess size. A rule without a `why` is not mergeable here.
- **Security rules tagged with their enforcing control** — `scope_freeze`, `bind_guard`,
  `literal_guard`, a CI job — or explicitly marked advisory. Only ~4.4% of security rules
  in public `CLAUDE.md` files have any matching control, and nothing tells the reader
  which (E-6). This repository has the controls; it can close that loop instead of
  reproducing the gap.
- **A defensive directive in the root guide**, which is a measured ~60% suppression of
  indirect-prompt-injection success (E-5) and costs three lines.
- **Mermaid where it encodes a constraint, not a structure.** Structure diagrams stay in
  `docs/C4.md` and `docs/architecture/`. A guide may carry **one** diagram, and only when
  it shows something the code cannot: bring-up ordering, codegen direction, a governance
  gate. Every diagram carries `accTitle`/`accDescr` and a prose summary.
- **One new roster agent, `docs-cartographer`, as a detector — not an author.** The only
  statistically significant success-rate finding in the literature is that LLM-generated
  context files are worse than developer-written ones (E-1, p = 0.038). The agent finds
  staleness and proposes diffs; a human ratifies content.
- **A Claude Code loading bridge**: the root `CLAUDE.md` pointer becomes an `@AGENTS.md`
  import, and each directory carrying a guide gains a three-line `CLAUDE.md` importing
  its sibling. Nested files load on demand, so the tree costs nothing at session start —
  and on-demand retrieval measurably beat always-on injection on cache footprint at equal
  correctness (E-2, p_Holm = 0.012).
- **A mechanical checker**, `tools/validate_agents_docs.py` — third sibling of
  `validate_workforce.py` and `validate_skills.py` — with a declared-exception mechanism
  in `.claude/governance.yaml`, matching `bind_guard` and `literal_guard` precedent.

## Invariants (binding on every task)

| # | Invariant | Source | Enforcement |
| - | --------- | ------ | ----------- |
| I-1 | A scoped guide may add a constraint; it may never relax or negate one the root sets | `docs/ROADMAP.md` M2 security invariant; CHARTER §4 | `validate_agents_docs` check 10 (negation detector) + review stop point |
| I-2 | `governance.c_gate_met` stays `false`; no glob list is edited | `.claude/governance.yaml`; CHARTER §6 | No task touches the file except to add an `agents_docs` exceptions block |
| I-3 | No guide file is written into a frozen path; no `MESHSA_GOVERNANCE_OVERRIDE` is spent on Markdown | design §D-10 (verified against `match_globs`) | `scope_freeze.py` denies it; manifest records `command/` as parent-covered |
| I-4 | No guide introduces an unauthenticated surface, weakens a fail-closed bind, or restates a security rule without naming its control | `docs/AUDIT_M2_AUTH.md`; E-6 | `validate_agents_docs` checks 11–13; `security-reviewer` before PR |
| I-5 | Every external research claim cites `docs/AGENTS_MD_EVIDENCE.md`, never a secondary summary, and carries its significance | `docs/OPENSPEC_M2_BUNDLE_PEER_REVIEW.md` F-1 | Review; the register is the only citable source |
| I-6 | New Python in `tools/` passes ruff, ruff format, mypy and pytest — `make checkers` alone is not the gate | CHARTER §4 Invariant 6; `.github/workflows/ci.yml` | `tasks.md` per-task gate sequence |

## Scope — what this change is NOT

- Not a re-drawing of `docs/C4.md` / `docs/architecture/C4.md`. Guides link; they never
  duplicate.
- Not a replacement for `.agents/skills/`. Skills stay the home for *workflows*; guides
  are the home for *place-bound traps*. Putting testing or workflow procedure in an
  always-loaded guide is Skill Leakage (E-7, 35% prevalence, most-leaked category).
- Not authoritative over `docs/specs/`. This bundle is additive governance.
- Not a source, transport, bind, or command-path change. `c_gate_met` stays `false`.
- Not a claim that guides improve task success. They do not, on the evidence (E-1, E-2).
  The claims made here are about cost, traps avoided, and injection surface controlled.

## Impact

| Area | Effect |
| ---- | ------ |
| New files | 30 `AGENTS.md` (35 total, 5 exist), 33 `CLAUDE.md` stubs (34 total, 1 exists — `.claude/` is exempt), 1 skill, 1 roster agent, 1 checker + its tests, 2 docs |
| Modified files | root `AGENTS.md`, root `CLAUDE.md`, 4 existing scoped guides, `.claude/governance.yaml` (new `agents_docs` exceptions block), `tools/Makefile`, `scripts/validate-pre-pr.sh`, `.github/workflows/ci.yml`, `.pre-commit-config.yaml`, `CONTRIBUTING.md`, `docs/specs/README.md`, `CHANGELOG.md` |
| Session-start context cost | +0 tokens. Only the root guide loads at launch, via the import; scoped guides load on demand |
| CI | One added step in the existing `governance` job; no new job, no new matrix |
| Security | **Non-trivial and declared.** +63 auto-loaded trusted-context files. Mitigated by checks 11–13 (action-directive rejection, Unicode hygiene, control tagging), a defensive root directive (~60% ASR suppression, E-5), and verified `CODEOWNERS` coverage. Separately, T-0.4 surfaces a **pre-existing** unaudited all-interfaces unauthenticated listener in `artifacts/api-server` and blocks that folder's guide until it is recorded in `docs/AUDIT_M2_AUTH.md` |
| Risk | Moderate, and front-loaded: the contract and checker land on 5 files before any new guide is written |

## Open calls for the maintainer (T-0.2)

Defaults are recorded and hold if no answer comes; each is a one-line manifest edit.

1. **Tier 2 breadth.** 15 subsystem guides are proposed. `src/meshsa/llm/` sits at the
   margin — its read-only-tool-surface property is a genuine security trap, but
   `packages/meshsa/AGENTS.md` could carry it. Included as proposed.
2. **The `CLAUDE.md` stub tree.** 34 new three-line files is the price of mechanical
   loading. Fallback if the count is unacceptable: Tier 0/1 stubs only (14 files),
   accepting prose-only discovery below that.
3. **Diagram relocation.** rev.2 moves structure diagrams out of guides into `docs/`.
   If per-folder structure diagrams are wanted regardless of E-1, say so and they return
   as an optional, budget-counted section — the plan should record that as a deliberate
   override of the evidence, not silently adopt it.
