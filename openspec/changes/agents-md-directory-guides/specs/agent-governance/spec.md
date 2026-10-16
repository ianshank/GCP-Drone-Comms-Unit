# Spec Delta: agent-governance

## MODIFIED Requirements

### Requirement: Agents Collaborate by Default
Amends the requirement of the same name ratified in
`openspec/changes/gcp-drone-m2-agent-hardening`. The binding `security-reviewer` rule and
the `Relationship:` marker are unchanged. What changes: the root `AGENTS.md` SHALL be
loaded mechanically rather than by prose reference, and every rule in an agent instruction
file SHALL carry its rationale. Where a rule is security-relevant it SHALL name the control
that enforces it — `scope_freeze`, `bind_guard`, `literal_guard`, or a CI job — or be
marked advisory, so a reader can tell enforcement from intention.

#### Scenario: Root guide not loaded
- **WHEN** the root `CLAUDE.md` references `AGENTS.md` by Markdown link rather than by
  `@AGENTS.md` import, and a `CLAUDE.md` exists at or above the working directory
- **THEN** no `AGENTS.md` in the repository is loaded, and the requirement is unmet
  regardless of what those files contain

#### Scenario: Security rule with no stated enforcement
- **WHEN** a guide or rule states a constraint about binds, tokens, credentials, or the
  frozen command path without a `control:` or `advisory` marker
- **THEN** `validate_agents_docs` exits non-zero, naming the file and the rule

## ADDED Requirements

### Requirement: Traps Are the Documented Content
Each of the five `AGENTS.md` guides SHALL carry a `## Traps` section. A trap is a fact that
costs an agent a wasted turn or a wrong result — a gate that fires on a partial run, an
ordering dependency, a file that regenerates, a predicate that looks equivalent and is not.
Repository overviews, structure maps and file inventories SHALL NOT be added as new
content: they are measurably ineffective where other documentation exists
(`docs/AGENTS_MD_EVIDENCE.md` E-1 §4.3), and this repository has `docs/C4.md`,
`docs/ARCHITECTURE.md` and `docs/specs/`.

Procedure — how to run a thing, regenerate a thing, or follow a workflow — SHALL live in
`.agents/skills/`, not in an always-loaded guide. This restates the standing policy in
`.github/copilot-instructions.md` rather than introducing one.

#### Scenario: Guide without traps
- **WHEN** one of the five guides has no `## Traps` section
- **THEN** `validate_agents_docs` exits non-zero, naming the file

#### Scenario: Procedure added to a guide
- **WHEN** a reviewer finds regenerate-with or run-this-command content in a guide rather
  than in the skill that owns that workflow
- **THEN** the review returns it to the skill, per `.github/copilot-instructions.md`

### Requirement: Every Rule Carries Its Rationale
Each line in a `## Rules` section SHALL carry a trailing `— why: <reason>` clause. Agentic
instruction files grow +226% over their lifetime, and deletion hazard *falls* with
instruction age because the rationale decays faster than the instruction; 77.3% of
instruction deaths arrive as wholesale rewrites. Recording the reason removed 99.3% of
excess size, and is the only remedy in the literature that is independent of file count
(`docs/AGENTS_MD_EVIDENCE.md` E-3).

#### Scenario: Rule without a rationale
- **WHEN** a `## Rules` line has no `why:` clause
- **THEN** the review returns it; a rule whose reason is unrecorded cannot later be safely
  deleted, so it is never deleted

### Requirement: Path-Scoped Rules for Fire-On-Open Cases
Traps that must reach an agent at the moment it opens a specific file — generated output,
vendored trees, read-only archives — SHALL be expressed as `.claude/rules/*.md` with
`paths:` frontmatter, not as an instruction file inside the directory concerned. A file
placed inside an orval `clean: true` output is deleted by the next codegen; a file placed
in the parent does not fire when the generated file is opened. A path-scoped rule does
both: it fires on the match and lives outside the deleted tree.

#### Scenario: Guard placed inside a generated directory
- **WHEN** an instruction file is committed under `lib/*/src/generated/` or
  `artifacts/mockup-sandbox/src/.generated/`
- **THEN** `validate_agents_docs` exits non-zero, directing the content to a `paths:` rule

#### Scenario: Agent opens a generated file
- **WHEN** an agent reads `lib/api-zod/src/generated/api.ts`
- **THEN** `.claude/rules/generated-code.md` loads, stating that the tree is orval output
  and that the source of truth is `lib/api-spec/openapi.yaml`

### Requirement: Citations State Why and When
Every repository-relative path an instruction file cites SHALL exist and SHALL carry the
reason to read it — a mentioned path with no stated purpose is commonly ignored
(`docs/AGENTS_MD_EVIDENCE.md` E-7). Path extraction SHALL cover backtick spans and Markdown
link targets, SHALL strip a trailing `[extras]`, `::symbol` and `#anchor`, SHALL reject
bare file-extension tokens and absolute paths, and SHALL resolve file-relative, then the
nearest `src/<pkg>/`, then repository-root-relative. Deliberate counter-example citations
SHALL be declarable with a rationale.

#### Scenario: Guide cites a path that does not exist
- **WHEN** a guide references `packages/meshsa/src/meshsa/federation/` and that directory
  is absent
- **THEN** `validate_agents_docs` exits non-zero, naming the file and the dead path

#### Scenario: Legitimate package-relative citation
- **WHEN** `packages/jetson_yolo_gcs/AGENTS.md` cites `detection/factory.py`, which
  resolves under that package's `src/jetson_yolo_gcs/`
- **THEN** the citation is accepted. Without the third resolution base this check emits
  nine false positives across the five existing guides, and a checker that cries wolf is
  not a gate

### Requirement: Instruction Files Are a Declared Injection Surface
`AGENTS.md` and `.claude/rules/*.md` are loaded by the harness as trusted system context
without inspection, which makes them the highest-privilege prompt-injection entry point in
an agentic repository, under a threat model that includes a pull-request contributor
(`docs/AGENTS_MD_EVIDENCE.md` E-5). They SHALL contain no bidirectional-override
(U+202A-E, U+2066-9) or zero-width (U+200B-D) code points, checked by exact code point. A
broader "ASCII-dominant" rule is deliberately not imposed: the authoring contract itself
mandates U+2014, U+00B7 and U+2264, so a density threshold would fire on its own format. `CODEOWNERS` SHALL cover `**/AGENTS.md`,
`**/CLAUDE.md` and `.claude/rules/**`; human review of the diff is the load-bearing control,
because the content scan E-5 recommends belongs to the harness. The root `AGENTS.md` SHALL
carry a defensive directive against acting on instructions found in repository content,
noting that its measured effect is on a different entry point from the one these files are.

#### Scenario: Hidden-Unicode payload
- **WHEN** an instruction file contains a zero-width or bidirectional-override code point
- **THEN** `validate_agents_docs` exits non-zero, naming the file and the offset

#### Scenario: Instruction file added outside code ownership
- **WHEN** `CODEOWNERS` no longer covers a path where instruction files may be added
- **THEN** T-0.4 fails and the phase stops; the surface has lost its only real control

### Requirement: The Checker Runs in CI and Owns No Governance Data
`tools/validate_agents_docs.py` SHALL be invoked by `make -f tools/Makefile checkers`, by
`scripts/validate-pre-pr.sh`, and by the CI `governance` job, and SHALL be wired into them
in the same phase that creates it. Its policy — the instruction-file list and any declared
exceptions — SHALL live in module constants and SHALL NOT be added to
`.claude/governance.yaml`, whose loader is Pydantic `extra="forbid"` and whose consumer
`scope_freeze.py` fails open on a config it cannot validate. A documentation entry must
never be able to stop the Initiative-C freeze from denying.

#### Scenario: Documentation data proposed for the governance config
- **WHEN** a change adds a documentation-shaped key to `.claude/governance.yaml`
- **THEN** it is rejected: a present-but-malformed block raises, the loader fails open, and
  the command freeze silently stops denying

#### Scenario: Guide tree regresses on a branch with no local run
- **WHEN** a PR lands a guide citing a path deleted in the same PR
- **THEN** the CI `governance` job fails, naming the file and the dead path

## Implementation notes (declared interpretations)

1. **Non-duplication is a review obligation, not a mechanical one.** Two detectors were
   specified and both measured: fuzzy matching scores a verbatim duplicate *below* every
   genuine non-duplicate, and normalised exact matching is defeated by line-wrapping and by
   partial copying. Neither is deployable. The obligation stands; the check does not.
2. **Line budgets are authoring guidance, not a gate.** The root `AGENTS.md` grows +16
   lines/month, measured in-repo and monotone. A gated budget would block every PR within
   60 days over prose unrelated to the change. E-1 Appendix B is an explicit null on
   length, so the budget never had a performance justification, and E-3 shows incremental
   deletion does not happen — a budget schedules the wholesale rewrite that accelerates the
   ratchet rather than preventing it.
3. **The checker validates structure, references and injection hygiene — not truth.** Four
   review rounds found two defects that mattered: a wrong `LANDING_TARGET` failure policy
   on the safety write path, present in two live documents, and an unaudited all-interfaces
   unauthenticated listener. Both were found by reading code. No check proposed in any
   revision would have caught either.
4. **No controlled study has evaluated nested per-directory context files**; the three that
   exist restrict to single-root configurations by design. Earlier revisions of this bundle
   proposed 35 such files anyway. This delta covers five guides that already exist plus six
   path-scoped rules, which is the smallest shape that still reaches an agent opening a
   generated file.
5. **Scope-freeze is cited, not re-legislated.** Its hook denies a write to a Markdown file
   inside `command_emission_globs` exactly as it denies one to a module — correct and
   unchanged. The frozen path's traps live in a `paths:` rule outside the frozen tree.