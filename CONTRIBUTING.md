# Contributing to GCP-Drone-Comms-Unit

Thanks for your interest in contributing.

## Repository layout

```text
packages/meshsa/      Python framework (src layout, all tests live here)
ops/                  Deployment kits (pi5-node, base-service)
hardware/             3D-printable cases and parts
docs/                 Architecture, audit report, design notes
tools/                Dockerfile, Makefile, build helpers
.github/workflows/    CI pipelines
archive/              Historical ZIP snapshots (do not edit)
```

## Development setup

```bash
python -m venv .venv
. .venv/bin/activate          # Windows: .\.venv\Scripts\Activate.ps1
pip install -e "packages/meshsa[dev]"
pre-commit install
```

For real-radio work, also install the optional extra:

```bash
pip install -e "packages/meshsa[dev,meshtastic]"
```

## Day-to-day commands

| Goal       | Command                                                   |
|------------|-----------------------------------------------------------|
| Test       | `make test` (or `cd packages/meshsa && pytest`)           |
| Lint       | `make lint` (`ruff check .`)                              |
| Format     | `make format` (`ruff format .`)                           |
| Type-check | `make type` (`cd packages/meshsa && mypy src`)            |
| Build      | `make build` (`python -m build packages/meshsa`)          |
| Container  | `make docker`                                             |

CI runs lint + type + test + build on every push and pull request.

AI coding agents should read [AGENTS.md](AGENTS.md) first, then any nested
`AGENTS.md` in the folder they edit. Repeatable agent workflows live under
[.agents/skills](.agents/skills).

## Branch / PR model

- Branch off `main`. Use `feat/`, `fix/`, `chore/`, `docs/` prefixes.
- Keep PRs small and focused. One logical change per PR.
- Coverage gate is **>=90%**; new code should keep the suite at 100%.
- Update `CHANGELOG.md` under `## [Unreleased]` for any user-visible change.
- Run `pre-commit run -a` and `make test lint type` locally before pushing.

### Required checks

A PR is mergeable when every `ci` workflow job is green: `test` (py3.10–3.12: ruff,
mypy, pytest with the coverage gate, build), `perception` (same for
`packages/jetson_yolo_gcs`), `governance` (hook tests, `bind_guard`, workforce lint,
gitleaks), and `shell` lint. Branch protection on `main` is expected to require these
four checks plus a CODEOWNERS review; pushing directly to `main` is blocked locally by
pre-commit (`no-commit-to-branch`).

### Flaky-test policy

Per-PR CI is deterministic by construction: Hypothesis runs the derandomized `ci`
profile, and the link-loss fuzz uses a fixed seed. The `nightly` workflow explores
randomized inputs (`HYPOTHESIS_PROFILE=nightly`, `print_blob` on). A nightly failure
files/updates a `nightly soak/fuzz failure` issue automatically; triage it within a
day using the `@reproduce_failure` decorator from the log. Do not retry-until-green:
a red on the derandomized profile is a real regression, never flake.

## Backward compatibility

Wire-format changes go through `meshsa.version`:

- Bump `SCHEMA_VERSION` for any envelope shape change.
- Raise `MIN_COMPATIBLE_SCHEMA` only when older nodes are intentionally cut off.
- Document the change and migration path in `CHANGELOG.md`.

## Reporting bugs / asking questions

Open a GitHub issue with reproduction steps, expected vs actual behavior, and
relevant logs (structlog output is preferred).
