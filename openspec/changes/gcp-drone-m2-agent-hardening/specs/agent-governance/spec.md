# Spec Delta: agent-governance

## ADDED Requirements

### Requirement: Scope-Freeze on Milestone and Command Surface
A PreToolUse hook SHALL deny Write/Edit operations that widen scope past M2
(`scope_widening_globs`) or touch the Initiative-C command emission path
(`command_emission_globs`) while `governance.c_gate_met` is `false`, unless
the configured override env var is set; overrides SHALL be logged with the
path and the denial reason.

#### Scenario: Edit to the command emission path while gated
- **WHEN** `c_gate_met` is `false` and an edit targets the command send path
- **THEN** the hook denies, quoting `NEXTSTEPS.md`: "do not ship a command
  surface before TLS + auth land"

#### Scenario: Override is loud
- **WHEN** the override env var is set non-empty and a frozen path is edited
- **THEN** the edit proceeds and a structured log line records the override,
  the path, and the reason that would have applied

### Requirement: Agents Collaborate by Default
`AGENTS.md` SHALL direct proactive subagent delegation, and the
`security-reviewer` SHALL review every diff touching `packages/` or any
transport before a PR is opened. Roster entries under `.claude/agents/` SHALL
declare their relationship to existing `.github/agents/` and `.agents/skills/`
entries via a `Relationship:` line; `tools/validate_workforce.py` enforces the
marker, the ≤60-line budget, frontmatter shape, name uniqueness, and that
referenced paths exist.

#### Scenario: Transport diff opened without security review
- **WHEN** a PR touches a transport module with no security-reviewer pass
  recorded
- **THEN** the review checklist flags it as incomplete

#### Scenario: Roster entry without a declared relationship
- **WHEN** a `.claude/agents/*.md` file lacks a `Relationship:` line or names
  a nonexistent path
- **THEN** `validate_workforce` exits non-zero, naming the file and reason

## Implementation notes (declared interpretations)

1. The scope-freeze hook governs edit-time behavior in Claude Code sessions;
   it cannot constrain human pushes outside sessions, and it deliberately
   fails open on malformed hook input. CI's `governance` job (bind-guard +
   hook tests) and charter review remain the backstop.
2. `c_gate_met` is a human-set config flag, not an inferred one — flipping it
   is a deliberate maintainer decision under the repo's "ratified per §6"
   convention (CHARTER §3: ratification "does not flip a switch"; §6 requires
   scope violations to be surfaced for a human decision).
3. The M2 security invariant this change enforces is stated in `ROADMAP.md`
   ("no unauthenticated surface is exposed by default"); the CHARTER's
   commanding carve-out adds the stricter clause that an unauthenticated
   command surface must never be exposed in a deployment.
