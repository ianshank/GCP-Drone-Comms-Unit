# Spec Delta: agent-governance

## ADDED Requirements

### Requirement: Tiered Per-Directory Agent Guides
The repository SHALL carry `AGENTS.md` guides on a committed tier manifest
rather than in every directory. A directory SHALL appear in the manifest only
if it has at least one of: a build/test/run command distinct from its parent's,
an invariant or hazard its parent file does not state, or a boundary invisible
from the file contents alone (generated code, a frozen path, a deployment
manifest, a read-only archive). `tools/validate_agents_docs.py` SHALL enforce
the manifest in both directions — a guide outside it and a manifest entry
without a guide are both findings.

#### Scenario: Guide added without a tier decision
- **WHEN** an `AGENTS.md` is committed in a directory absent from `TIER_MANIFEST`
- **THEN** `validate_agents_docs` exits non-zero, naming the path and stating
  that a tier and a qualifying reason must be recorded first

#### Scenario: Manifest entry never written
- **WHEN** `TIER_MANIFEST` lists a directory that has no `AGENTS.md`
- **THEN** `validate_agents_docs` exits non-zero, naming the missing file

### Requirement: Guide Structure and Line Budget
Every `AGENTS.md` SHALL carry an H1 title, a breadcrumb line naming its scope
and linking its parent guide, and the H2 sections required for its tier in the
canonical order `Purpose`, `Map`, `Key files`, `Rules`, `Commands`, `Subagents`,
`Verification` (Tier 3 guard files carry `Purpose` and `Rules` only). Total
line count SHALL stay within the tier budget: 150 for the root, 80 for a domain
root, 60 for a subsystem, 12 for a guard file.

#### Scenario: Sections out of order or missing
- **WHEN** a Tier 1 guide omits `## Commands` or places `## Rules` before `## Purpose`
- **THEN** `validate_agents_docs` exits non-zero, naming the file and the
  expected order

#### Scenario: Guide exceeds its tier budget
- **WHEN** a subsystem guide reaches 61 lines
- **THEN** `validate_agents_docs` exits non-zero, naming the file, its count,
  and its budget

### Requirement: Scoped Guides Are Additive and Non-Duplicating
A scoped `AGENTS.md` SHALL state only what is true in its own subtree. A rule
that holds repository-wide SHALL live in the root `AGENTS.md` and nowhere else.
A scoped guide MAY add a constraint; it SHALL NOT relax or negate one the root
sets. Every repository-relative path a guide cites SHALL exist, and every
`make`, `pnpm run`, or `npm run` command it lists SHALL name a real target or
script.

#### Scenario: Root rule restated in a scoped guide
- **WHEN** a scoped guide's `## Rules` contains a line that near-duplicates a
  root `AGENTS.md` rule
- **THEN** `validate_agents_docs` exits non-zero, naming both files and the
  duplicated line

#### Scenario: Guide cites a path that no longer exists
- **WHEN** a guide references `packages/meshsa/src/meshsa/federation/` after
  that directory is removed or was never created
- **THEN** `validate_agents_docs` exits non-zero, naming the file and the dead
  path

#### Scenario: Guide lists a command that does not exist
- **WHEN** a guide's `## Commands` names `make coverage-all` and no such target
  exists in `Makefile` or `tools/Makefile`
- **THEN** `validate_agents_docs` exits non-zero, naming the file and the
  command

### Requirement: Accessible, Scoped Diagrams
Every Mermaid block in an `AGENTS.md` SHALL declare `accTitle:` and `accDescr:`,
SHALL be followed immediately by a one-sentence prose summary of what it shows,
and SHALL stay within 15 nodes. A diagram SHALL depict its own folder's
boundary — what enters, what leaves, and the seam between them — and SHALL NOT
restate the system-level architecture owned by `docs/C4.md`. Tier 0 and Tier 1
guides SHALL carry a diagram; Tier 3 guard files SHALL NOT.

#### Scenario: Diagram without an accessible description
- **WHEN** a guide contains a ```mermaid block with no `accDescr:` line
- **THEN** `validate_agents_docs` exits non-zero, naming the file and the block

#### Scenario: Diagram with no prose summary
- **WHEN** a Mermaid block's closing fence is followed by a heading or another
  fence rather than a prose line
- **THEN** `validate_agents_docs` exits non-zero, naming the file

#### Scenario: Guard file carries a diagram
- **WHEN** a Tier 3 guide contains a ```mermaid block
- **THEN** `validate_agents_docs` exits non-zero, stating that guard files are
  prose-only

### Requirement: Delegation Is Discoverable From the Folder
Every Tier 0–2 `AGENTS.md` SHALL carry a `## Subagents` section naming the
subagents, skills, and custom agent modes that apply to work in that folder.
Every entry SHALL resolve to an existing `.claude/agents/*.md`,
`.agents/skills/*/SKILL.md`, or `.github/agents/*.agent.md`. A guide SHALL NOT
introduce a subagent, skill, or mode that does not exist. Where the root's
binding `security-reviewer` rule governs a folder, that folder's guide SHALL
restate it as an additive constraint.

#### Scenario: Subagent reference does not resolve
- **WHEN** a `## Subagents` entry names `transport-auditor` and no roster file,
  skill, or agent mode by that name exists
- **THEN** `validate_agents_docs` exits non-zero, naming the file and the
  unresolved reference

#### Scenario: Transport folder guide omits the security gate
- **WHEN** the guide for a folder under `packages/` or any transport has a
  `## Subagents` section that does not name `security-reviewer`
- **THEN** `validate_agents_docs` exits non-zero, citing the root `AGENTS.md`
  binding rule

### Requirement: Guides Load Mechanically in Claude Code
The root `CLAUDE.md` SHALL import the root `AGENTS.md` with `@AGENTS.md` rather
than only linking to it, and every directory carrying an `AGENTS.md` SHALL carry
a `CLAUDE.md` that imports its sibling. A guide's content SHALL live in the
`AGENTS.md`; the paired `CLAUDE.md` SHALL contain only the import and a title.

#### Scenario: Guide added without its pairing
- **WHEN** an `AGENTS.md` is committed with no sibling `CLAUDE.md`, or with one
  that does not import `@AGENTS.md`
- **THEN** `validate_agents_docs` exits non-zero, naming the directory

#### Scenario: Content drifts into the stub
- **WHEN** a paired `CLAUDE.md` grows rules, commands, or a diagram of its own
- **THEN** `validate_agents_docs` exits non-zero, stating that the stub carries
  only a title and the import

### Requirement: Documenting a Frozen Path Does Not Unfreeze It
Guidance covering a directory under `governance.command_emission_globs` or
`governance.scope_widening_globs` SHALL be written in that directory's parent
guide. `MESHSA_GOVERNANCE_OVERRIDE` SHALL NOT be used to place a documentation
file inside a frozen path.

#### Scenario: Guide written into the frozen command path
- **WHEN** an agent attempts to write
  `packages/meshsa/src/meshsa/command/AGENTS.md` while `c_gate_met` is `false`
- **THEN** the scope-freeze hook denies it, and the guidance is placed in
  `packages/meshsa/src/meshsa/AGENTS.md` under a `command/ (frozen)` subsection
  instead

### Requirement: The Guide Tree Has an Owner
`.claude/agents/` SHALL carry a `docs-cartographer` entry that owns authoring
and refreshing the guide tree and its diagrams, declares its `Relationship:` to
`.agents/skills/agents-md-authoring/SKILL.md`, and holds documentation-scoped
tools only — no test, build, or git authority. `CONTRIBUTING.md` SHALL require a
PR that adds, removes, or moves a module in a covered folder to refresh that
folder's `## Key files` table in the same PR.

#### Scenario: Module added without a guide refresh
- **WHEN** a PR adds a module to a folder with an `AGENTS.md` and leaves the
  `## Key files` table unchanged
- **THEN** the PR checklist flags it as incomplete and `docs-cartographer` is
  the named owner of the fix

## Implementation notes (declared interpretations)

1. `tools/validate_agents_docs.py` validates **structure and references**, not
   prose quality. Whether a rule is worth stating remains a review judgement;
   the checker cannot detect a guide that is well-formed and wrong. The owner
   requirement above exists because of that gap, not in spite of it.
2. The duplication check (check 10) is a *near*-duplicate heuristic over
   normalised rule lines. It will produce occasional false positives on short
   rules; the remedy is to reword or to move the rule to the root, never to
   widen the threshold until the check stops firing.
3. The `security-reviewer` scenario restates an existing binding rule from the
   root `AGENTS.md` (ratified in `gcp-drone-m2-agent-hardening`). It is
   additive — this change makes the rule visible where the work happens, and
   introduces no new review obligation.
4. Claude Code's `AGENTS.md` support depends on the harness: reading `AGENTS.md`
   directly requires v2.1.277 or later, and some sessions cannot read it at all.
   The `@AGENTS.md` import required above is the mechanism that works in every
   session, which is why it is specified rather than the
   `instructionFiles: claude-md-and-agents-md` setting — Claude Code ignores
   that setting in project and local settings files, so it cannot be committed
   on the team's behalf.
5. The line budgets are set from this repository's own practice (existing
   scoped guides run 25–67 lines; the root runs 135) rather than from the
   looser public guidance of 200–500 lines. They are deliberately tight: the
   failure mode being defended against is accretion, and a budget that is never
   reached does not defend against it.
6. Tier 3 guard files are the one case where near-total redundancy is
   intentional. Their whole value is firing at the moment an agent reads a
   generated file, which is exactly when the parent guide is least likely to be
   in context.
