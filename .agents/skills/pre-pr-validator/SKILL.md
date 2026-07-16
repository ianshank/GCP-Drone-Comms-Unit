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
2. **Run quality gates for both packages** — a change touching only one package still needs that
   package's own gates run from its own directory (each has a package-local `pyproject.toml`
   with its own ruff/mypy/coverage config; running from the repo root can read the wrong one):
   - **`packages/meshsa`** (enforces **97%+** total coverage, `--cov-fail-under=97`):
     ```
     cd packages/meshsa
     python -m pytest
     ruff check .
     ruff format --check .
     mypy src
     python -m build
     ```
   - **`packages/jetson_yolo_gcs`** (enforces **96%+** total coverage, `--cov-fail-under=96`;
     self-contained, must not `import meshsa`):
     ```
     cd packages/jetson_yolo_gcs
     python -m pytest
     ruff check .
     ruff format --check .
     mypy src
     python -m build
     ```
   Both packages share the same ruff rule selection (`select = [E, F, I, UP, B, SIM]`) and run
   `mypy --strict`. If the diff also touches `jetson_yolo_gcs`, confirm no `import meshsa` was
   introduced (grep for it) — that's a hard invariant, not a style preference.
3. **Analyze coverage**: Parse coverage details to check if any modified or added file falls below the coverage target for its package (97% meshsa / 96% jetson_yolo_gcs).
4. **Produce Gap Report**: Generate a structured markdown report detailing:
   - Changed files missing test coverage.
   - Quality/lint/type errors found (if any), per package.
   - Recommended documentation updates (CHANGELOG.md, README.md, C4.md, ARCHITECTURE.md, NEXTSTEPS.md).
5. **Verify zero hardcoded values**: Confirm all operational values are config fields with default values and env-var bindings.
6. **No-numpy invariant (bounded exception: the tracker backend)**: the base package and all pure
   logic (e.g. `geometry/ned.py`) stay numpy-free. The **sole** permitted numpy use is inside the
   optional Norfair tracker backend (`tracking/norfair_backend.py`), where numpy is a lazy,
   `[tracker]`-extra-gated **transitive** dep of `norfair` (never declared in `dependencies`, never
   imported at package import — `tests/unit/test_imports_clean.py` locks both `numpy` and
   `norfair` out of `import jetson_yolo_gcs`). Any numpy import **outside** that backend, or any
   `numpy` added to `[project.dependencies]`, is a regression, not a judgment call. Confirm the
   diff introduces no such import and that base `import jetson_yolo_gcs` stays clean.

## References

- `AGENTS.md` (root directory)
- `packages/jetson_yolo_gcs/AGENTS.md` (package-local gates + failure policy)
- `docs/NEXTSTEPS.md`
- `packages/meshsa/pyproject.toml` (`--cov-fail-under=97`)
- `packages/jetson_yolo_gcs/pyproject.toml` (`--cov-fail-under=96`)
