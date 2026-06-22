---
name: pre-pr-validator
description: "Use when: running pre-PR checks, performing regression testing, validating ruff linting/formatting, verifying mypy type safety, and checking test coverage before pushing."
argument-hint: "Branch diff and verification gates to run"
---

# Pre-PR Validator

## When to Use

- Before committing changes and pushing a pull request to `main`.
- To generate a deterministic quality gap report.
- To verify ruff, mypy, pytest, and package build status locally.

## Procedure

1. **Identify branch diff**: Run `git diff main..HEAD --stat` (or `git diff main --stat`) to see which files have changed.
2. **Run quality gates**:
   - Pytest suite: `cd packages/meshsa && python -m pytest` (enforces 90%+ total coverage).
   - Ruff lint check: `ruff check .`
   - Ruff format check: `ruff format --check .`
   - Mypy type check: `mypy src`
   - Package build check: `python -m build`
3. **Analyze coverage**: Parse coverage details to check if any modified or added file falls below the coverage target.
4. **Produce Gap Report**: Generate a structured markdown report detailing:
   - Changed files missing test coverage.
   - Quality/lint/type errors found (if any).
   - Recommended documentation updates (CHANGELOG.md, README.md, C4.md, ARCHITECTURE.md, NEXTSTEPS.md).
5. **Verify zero hardcoded values**: Confirm all operational values are config fields with default values and env-var bindings.

## References

- `AGENTS.md` (root directory)
- `docs/NEXTSTEPS.md`
- `packages/meshsa/pyproject.toml`
