---
name: spec-driven-change
description: "Use when: starting a roadmap/initiative feature, new milestone work, a transport/codec/backend that adds behavior, or any change big enough to need a design. Author or update a spec under docs/specs first; code cites the spec by section."
argument-hint: "The feature/initiative, the milestone or plan track, and the seams it touches"
---

# Spec-Driven Change

## When to Use

- Beginning any ROADMAP milestone or initiative item, or a feature in
  [docs/IMPLEMENTATION_PLAN.md](../../../docs/IMPLEMENTATION_PLAN.md).
- Adding behavior that future agents must understand (new wire shape, safety path,
  service, backend, or non-trivial config surface).
- Before — not after — writing the implementation.

## Procedure

1. Read [../../../docs/CHARTER.md](../../../docs/CHARTER.md) (scope + invariants),
   [../../../docs/ROADMAP.md](../../../docs/ROADMAP.md) (milestone),
   [../../../docs/IMPLEMENTATION_PLAN.md](../../../docs/IMPLEMENTATION_PLAN.md) (track), and the
   nearest scoped `AGENTS.md`.
2. Copy [../../../docs/specs/TEMPLATE.md](../../../docs/specs/TEMPLATE.md) to
   `docs/specs/<slug>.md`. Fill **every** section — do not skip the config-field table (§5,
   no magic numbers), the wire/schema posture (§6), the test plan by category (§7), or the
   CHARTER §4 invariant checklist (§9).
3. Register the spec in [../../../docs/specs/README.md](../../../docs/specs/README.md) with
   status `Definition`.
4. Implement behind the seams (registry / `Protocol` / config); cite the spec's `§` numbers in
   docstrings (the FPV modules and `meshsa.command` already do this).
5. When the gates are green and coverage meets the spec floor, update `CHANGELOG.md` +
   `NEXTSTEPS.md` and move the spec status to `Implemented` (`Validated` after the spec's
   hardware/bench exit criteria pass).

## OpenSpec bundle reconciliation

For work tracked by an `openspec/changes/<bundle>/tasks.md` checklist:

- **Same-commit checkboxes**: the commit that lands a task ticks its `[x]` in the
  same commit. Name the task id(s) at the start of the commit subject
  (`T-2.3a: …`, `T-2.7/T-2.9: …`) so `tools/check_task_sync.py` can reconcile.
- **Split-task convention**: when a commit delivers only part of a task, split it
  into `T-x.ya` (what actually landed, ticked with the evidence commit SHA) and
  `T-x.yb` (the residual, unticked with a one-line reason) instead of leaving the
  original box ambiguously unchecked — the honest-partial pattern used across
  Phase 2 of `code-hygiene-modularity`.
- **Reconcile before a PR**: run `python tools/check_task_sync.py` (advisory —
  wired into `validate-pre-pr.sh`); every warning is either a checkbox to tick or
  a subject/bundle mismatch to explain in the PR body. Move the script's baseline
  forward when a bundle archives.

## Anti-patterns

- Implementing first and back-filling a spec to match — the spec is the design, not a summary.
- "No magic numbers" skipped: every operational value is a config field with an explicit
  default; fixed protocol constants are named module constants, not config.
- Silently changing CHARTER/ROADMAP. If the work needs a scope change, **stop and surface it**
  (CHARTER §6) rather than editing the stable docs in passing.

## References

- `docs/specs/README.md`, `docs/specs/TEMPLATE.md`
- `docs/specs/PHASE1_SPEC_v1_1.md` (worked example; code cites `§5.1` etc.)
- `docs/IMPLEMENTATION_PLAN.md` (the queued specs to author)
- `docs/CHARTER.md` §4 (the invariant checklist every spec answers)
