# Spec Delta: agent-governance

## MODIFIED Requirements

### Requirement: Agents Collaborate by Default
Amends the requirement of the same name ratified in
`openspec/changes/gcp-drone-m2-agent-hardening`. The binding `security-reviewer` rule and
the `Relationship:` marker are unchanged. What changes: the root `AGENTS.md` SHALL state
each repository-wide rule **once**, and a scoped guide SHALL NOT restate it. Delegation is
made discoverable at the folder instead by a `## Subagents` section naming the agents,
skills and modes that apply there. Where a rule is security-relevant, it SHALL name the
control that enforces it — `scope_freeze`, `bind_guard`, `literal_guard`, or a CI job — or
be marked advisory, so a reader can tell enforcement from intention.

#### Scenario: Repository-wide rule restated in a scoped guide
- **WHEN** a scoped guide's `## Rules` contains a normalised exact duplicate of a root
  `AGENTS.md` rule
- **THEN** `validate_agents_docs` exits non-zero, naming both files and the line

#### Scenario: Security rule with no stated enforcement
- **WHEN** a guide states a rule about binds, tokens, credentials, or the frozen command
  path without a `control:` or `advisory` marker
- **THEN** `validate_agents_docs` exits non-zero, naming the file and the rule

## ADDED Requirements

### Requirement: Tiered Guide Manifest
`AGENTS.md` guides SHALL exist only at directories listed in a committed tier manifest,
and every manifest entry SHALL have a guide. A directory qualifies only if it holds a
trap: a fact an agent gets wrong by default that its nearest ancestor guide does not
state. The manifest SHALL live as a module constant in `tools/validate_agents_docs.py`,
not in `.claude/governance.yaml`, because that file is loaded by the fail-open
`scope_freeze` hook and a documentation entry must never be able to invalidate the config
the Initiative-C freeze depends on. Enumeration SHALL use `git ls-files` so an untracked
or ignored guide is a finding rather than an invisible file.

#### Scenario: Guide added without a tier decision
- **WHEN** an `AGENTS.md` is committed in a directory absent from `TIER_MANIFEST`
- **THEN** `validate_agents_docs` exits non-zero, naming the path

#### Scenario: Manifest entry never written
- **WHEN** `TIER_MANIFEST` lists a directory that has no tracked `AGENTS.md`
- **THEN** `validate_agents_docs` exits non-zero, naming the missing file

#### Scenario: Guide placed where tooling will delete it
- **WHEN** a manifest entry names a directory that is an orval `clean: true` output or is
  rewritten by a generator on build
- **THEN** `validate_agents_docs` exits non-zero, directing the guide to the parent

### Requirement: Guide Structure and Line Budget
Every guide SHALL carry an H1 title, a breadcrumb naming its scope and linking its parent
guide, and exactly the H2 sections required for its tier, in this order:

| Tier | Required sections | Budget |
| ---- | ----------------- | ------ |
| 0 | `Purpose`, `Traps`, `Rules`, `Commands`, `Subagents` | ≤170 lines |
| 1 | `Purpose`, `Traps`, `Rules`, `Subagents` | ≤80 lines |
| 2 | `Traps`, `Rules`, `Subagents` | ≤60 lines |
| 3 | `Purpose`, `Rules` | ≤12 lines |

`Commands` and `Map` are optional at tiers 1 and 2 and forbidden at tier 3. Sections
SHALL appear in the order above with optional sections interleaved at their canonical
position. Line count includes blank lines and fenced blocks.

#### Scenario: Required section missing
- **WHEN** a Tier 1 guide has no `## Traps` section
- **THEN** `validate_agents_docs` exits non-zero, naming the file and the missing section

#### Scenario: Sections out of canonical order
- **WHEN** a guide places `## Rules` before `## Traps`
- **THEN** `validate_agents_docs` exits non-zero, naming the expected order

#### Scenario: Guide exceeds its tier budget
- **WHEN** a subsystem guide reaches 61 lines
- **THEN** `validate_agents_docs` exits non-zero, naming the file, its count and its budget

### Requirement: Every Rule Carries Its Rationale
Each line in a guide's `## Rules` SHALL carry a trailing `— why: <reason>` clause.
Agentic context files grow +226% over their lifetime and deletion hazard falls with
instruction age because an instruction's rationale decays faster than the instruction; a
rule whose reason is lost cannot be safely deleted, so it is never deleted
(`docs/AGENTS_MD_EVIDENCE.md` E-3).

#### Scenario: Rule without a rationale
- **WHEN** a `## Rules` line has no `why:` clause
- **THEN** `validate_agents_docs` exits non-zero, naming the file and the line

### Requirement: Scoped Guides Are Additive
A scoped guide MAY add a constraint. It SHALL NOT relax, negate, or carve an exception out
of a rule the root `AGENTS.md` sets. This is invariant I-1 and carries the M2 security
posture into every subtree.

#### Scenario: Scoped guide negates a root rule
- **WHEN** a scoped guide's `## Rules` names the subject of a root rule inside a negating
  construction — "does not apply here", "except in this folder", "unlike the root"
- **THEN** `validate_agents_docs` exits non-zero, naming both files and the line

### Requirement: Citations State Why and When
Every repository-relative path a guide cites SHALL exist, and SHALL be accompanied by the
reason to read it. A bare path reference is the Blind Reference smell: a mentioned path
that carries no purpose is commonly ignored (`docs/AGENTS_MD_EVIDENCE.md` E-7). Path
extraction SHALL cover both backtick spans and Markdown link targets, and SHALL resolve
file-relative before repository-root-relative.

#### Scenario: Guide cites a path that does not exist
- **WHEN** a guide references `packages/meshsa/src/meshsa/federation/` and that directory
  is absent
- **THEN** `validate_agents_docs` exits non-zero, naming the file and the dead path

#### Scenario: Citation carries no reason to read
- **WHEN** a guide's only reference to a document is its path, with no clause saying when
  or why to open it
- **THEN** `validate_agents_docs` exits non-zero, naming the file and the citation

### Requirement: Commands Resolve to Real Targets
Every `make`, `pnpm run`, or `npm run` command a guide lists SHALL name a real target or
script. `make` resolution SHALL disambiguate the root `Makefile` from `tools/Makefile` by
the presence of `-f`, because the two share eight target names with different meanings and
a union rule would pass a guide that sends an agent to the wrong test suite. Recursive
pnpm invocations and path-glob filters SHALL be skipped rather than guessed at. A guide
that lists an `npm run` command SHALL be a finding, since the repository's `preinstall`
script rejects non-pnpm agents.

#### Scenario: Guide lists a target that does not exist
- **WHEN** a guide's `## Commands` names `make coverage-all` and no such target exists
- **THEN** `validate_agents_docs` exits non-zero, naming the file and the command

#### Scenario: Guide names a colliding target without disambiguating
- **WHEN** `packages/meshsa/AGENTS.md` lists `make test`, which resolves in the root
  `Makefile` to the TypeScript suite rather than pytest
- **THEN** `validate_agents_docs` exits non-zero, requiring the `-f tools/Makefile` form

### Requirement: Accessible, Constraint-Bearing Diagrams
A guide MAY carry at most one diagram, and only where it encodes a constraint that cannot
be read from the code — an ordering dependency, a generation direction, a governance gate.
Structure and architecture diagrams belong in `docs/`; repository overviews in a context
file are not measurably useful where other documentation exists
(`docs/AGENTS_MD_EVIDENCE.md` E-1). Every diagram SHALL declare `accTitle` and `accDescr`,
SHALL be followed immediately by a prose summary, SHALL use `flowchart` or
`sequenceDiagram`, and SHALL keep its fence body within 22 lines. Tier 3 guides SHALL
carry none.

#### Scenario: Diagram without an accessible description
- **WHEN** a guide contains a fenced `mermaid` block with no `accDescr` line
- **THEN** `validate_agents_docs` exits non-zero, naming the file and the block

#### Scenario: Diagram with no prose summary
- **WHEN** the first non-blank line after a diagram's closing fence begins with `#`, a
  fence, a table pipe, or a list marker
- **THEN** `validate_agents_docs` exits non-zero, naming the file

#### Scenario: Diagram exceeds its fence budget
- **WHEN** a diagram's fence body reaches 23 lines
- **THEN** `validate_agents_docs` exits non-zero, naming the file and the count

#### Scenario: Guard file carries a diagram
- **WHEN** a Tier 3 guide contains a fenced `mermaid` block
- **THEN** `validate_agents_docs` exits non-zero, stating that guard files are prose-only

### Requirement: Delegation References Resolve
Every `## Subagents` entry SHALL name an existing `.claude/agents/*.md`,
`.agents/skills/*/SKILL.md`, or `.github/agents/*.agent.md`. The name SHALL be the first
backtick span of the bullet, so the reference is mechanically extractable. Every roster
agent, skill, and custom mode SHALL be named by at least one guide, so a newly added one
cannot drift unlisted.

#### Scenario: Subagent reference does not resolve
- **WHEN** a `## Subagents` entry names `transport-auditor` and no roster file, skill, or
  mode by that name exists
- **THEN** `validate_agents_docs` exits non-zero, naming the file and the reference

#### Scenario: Roster entry named by no guide
- **WHEN** a new `.claude/agents/*.md` lands and no guide's `## Subagents` names it
- **THEN** `validate_agents_docs` exits non-zero, naming the unreferenced entry

#### Scenario: Guide governing packages/ omits the security gate
- **WHEN** a Tier 0–2 guide for a directory under `packages/` has a `## Subagents` section
  that does not name `security-reviewer`
- **THEN** `validate_agents_docs` exits non-zero, citing the root binding rule.
  Tier 3 guides carry no `## Subagents` section and are outside this scenario

### Requirement: The Guide Tree Is a Declared Injection Surface
Instruction files are loaded by the harness as trusted system context without inspection,
which makes them the highest-privilege prompt-injection entry point in an agentic
repository, under a threat model that includes a pull-request contributor
(`docs/AGENTS_MD_EVIDENCE.md` E-5). Guides SHALL therefore contain no imperative action
directive outside the declared `## Commands` section, SHALL be ASCII-dominant, and SHALL
contain no bidirectional-override or zero-width characters. The root `AGENTS.md` SHALL
carry a defensive directive against acting on instructions found in repository content.

#### Scenario: Action directive outside the command allowlist
- **WHEN** a guide's `## Traps` or `## Rules` contains an imperative shell invocation
- **THEN** `validate_agents_docs` exits non-zero, naming the file and the directive

#### Scenario: Hidden-Unicode payload
- **WHEN** a guide contains a zero-width or bidirectional-override character
- **THEN** `validate_agents_docs` exits non-zero, naming the file and the offset

#### Scenario: Root guide without a defensive directive
- **WHEN** the root `AGENTS.md` carries no directive against acting on instructions
  embedded in repository content
- **THEN** `validate_agents_docs` exits non-zero

### Requirement: Guides Load Mechanically in Claude Code
The root `CLAUDE.md` SHALL import the root `AGENTS.md` with `@AGENTS.md` rather than
linking to it. Every directory carrying a guide SHALL carry a `CLAUDE.md` importing its
sibling, containing only a title and the import, **except** the repository root, which
keeps its Claude-specific notes, and `.claude/`, where a `CLAUDE.md` would be resolved as
a second repository-root-scope instruction file with undefined precedence. A guide and its
stub SHALL land in the same commit.

#### Scenario: Guide added without its pairing
- **WHEN** an `AGENTS.md` outside the root and `.claude/` is committed with no sibling
  `CLAUDE.md`, or with one that does not import `@AGENTS.md`
- **THEN** `validate_agents_docs` exits non-zero, naming the directory

#### Scenario: Content drifts into a stub
- **WHEN** a paired `CLAUDE.md` outside the root exceeds two non-blank lines
- **THEN** `validate_agents_docs` exits non-zero, naming the file

### Requirement: The Checker Runs in CI
`tools/validate_agents_docs.py` SHALL be invoked by `make -f tools/Makefile checkers`, by
`scripts/validate-pre-pr.sh`, and by the CI `governance` job, and SHALL be wired into the
first two in the same phase that creates it. A checker that exists but runs only when
someone remembers it is not a gate. Declared exceptions SHALL live in
`.claude/governance.yaml` under an optional `agents_docs` key with a rationale per entry,
matching `bind_guard` and `literal_guard` precedent, so that a false positive has a
reviewable escape rather than forcing a reword.

#### Scenario: Guide tree regresses on a branch with no local run
- **WHEN** a PR lands a guide citing a path deleted in the same PR
- **THEN** the CI `governance` job fails, naming the file and the dead path

#### Scenario: Exception without a rationale
- **WHEN** an `agents_docs` exception entry omits its rationale
- **THEN** the governance loader rejects the config

### Requirement: The Guide Tree Has an Owner
`.claude/agents/` SHALL carry a `docs-cartographer` entry that detects staleness in the
guide tree and proposes diffs, declares its `Relationship:` to
`.agents/skills/agents-md-authoring/SKILL.md`, and holds read-and-report tools only — no
`Write`, no `Edit`. LLM-generated context files are the one condition measured to perform
significantly worse than developer-written ones (`docs/AGENTS_MD_EVIDENCE.md` E-1,
p = 0.038), so the agent SHALL NOT land guide prose unreviewed, and SHALL NOT propose
deleting a rule carrying a `control:` marker.

#### Scenario: Owner entry with write authority
- **WHEN** `docs-cartographer`'s frontmatter lists `Write` or `Edit`
- **THEN** `validate_workforce` exits non-zero, naming the file and the tool

#### Scenario: Module added without a guide refresh
- **WHEN** a PR adds a module to a folder with an `AGENTS.md` and leaves its `## Traps`
  unchanged
- **THEN** the `CONTRIBUTING.md` PR checklist flags it as incomplete

## Implementation notes (declared interpretations)

1. The scope-freeze requirement ratified in `gcp-drone-m2-agent-hardening` is **cited, not
   re-legislated**. Its hook denies a write to a Markdown file inside
   `command_emission_globs` exactly as it denies one to a module, which is correct and
   unchanged. This bundle's obligation is narrower: document the frozen path from its
   parent, and do not spend `MESHSA_GOVERNANCE_OVERRIDE` on documentation. The hook cannot
   detect a file's intent, so that half is a review rule, not a mechanism.
2. `validate_agents_docs` validates structure, references and injection hygiene — **not**
   whether a rule is true or worth stating. Adversarial review of this bundle's own
   manifest found two plausible-and-wrong invariants that no checker would catch. The
   review stop points exist for that class, and `security-reviewer` remains binding before
   any PR.
3. Check 10 is a **normalised exact-match** plus a negation detector, not a similarity
   heuristic. Measured against this repository's corpus, `SequenceMatcher` scores a
   verbatim duplicate at 0.28 — below every one of 17 genuine non-duplicates — so no
   threshold separates the classes. Tier 3 is exempt from the duplicate half; near-total
   redundancy there is its purpose.
4. Claude Code's `AGENTS.md` support is version- and session-dependent, and the
   `instructionFiles` setting is ignored in project and local settings files. The
   `@AGENTS.md` import is specified because it is the mechanism that works in every
   session that can read a `CLAUDE.md` at all. The precise minimum version is not asserted
   here; the import does not depend on it.
5. The line budgets are set from this repository's own practice (existing guides 25–67
   lines, root 135) and from the growth ratchet in `docs/AGENTS_MD_EVIDENCE.md` E-3 —
   **not** from a measured relationship between length and outcome, which E-1's Appendix B
   explicitly rules out. A budget is a forcing function for review, not a performance
   tuning knob.
6. Tier 3 guard files are the one case where near-total redundancy is intentional: their
   value is firing at the moment an agent opens a generated file, which is exactly when
   the parent guide is least likely to be in context.
7. No controlled study has evaluated nested per-directory context files; the three that
   exist restrict to single-root configurations by design. Every requirement here is
   risk management for a design the evidence neither supports nor refutes, and is written
   to be reversible one manifest entry at a time.
