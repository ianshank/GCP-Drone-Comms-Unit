# Contributing to GCP-Drone-Comms-Unit

Thanks for your interest in contributing.

## Repository layout

```text
packages/meshsa/           Python framework (src layout + its tests)
packages/jetson_yolo_gcs/  On-board perception package (src layout + its tests)
flightctl/                 Live-service glue: gateway/commander runners, sim, systemd units
ops/                       Deployment kits (pi5-node, base-service, observability)
hardware/                  3D-printable cases and parts
docs/                      Architecture, audits, specs (docs/specs/), design notes
openspec/                  OpenSpec change bundles (proposal/design/tasks per change)
tools/                     Dockerfile, Makefile, governance hooks + checkers, build helpers
.github/workflows/         CI pipelines
archive/                   Historical ZIP snapshots (do not edit)
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
[.agents/skills](.agents/skills), and path-scoped rules under
[.claude/rules](.claude/rules) load when a file they match is opened.

If you edit an `AGENTS.md` or a `.claude/rules/*.md`, run
`python tools/validate_agents_docs.py`. It checks the things that otherwise fail
silently: a cited path that no longer resolves, a rule with no recorded reason, a
security rule that names no enforcing control, a hidden Unicode code point, and — for
a rule file — a missing or misspelled `paths:` key (which makes the rule load in
*every* session instead of none) or a `paths:` glob that matches nothing (which makes
it load in none). It is stdlib-only, runs in well under a second, and is wired into
`make -f tools/Makefile checkers`, `make validate-pre-pr`, pre-commit, and CI.

Note for your own setup: Claude Code reads `AGENTS.md` only because `CLAUDE.md`
imports it with `@AGENTS.md`. Under the default instruction mode, a `CLAUDE.md`
anywhere at or above the working directory means `AGENTS.md` files are not loaded on
their own — a Markdown link to it does **not** work. Other harnesses (Codex, Copilot,
Cursor) read `AGENTS.md` directly and do not read `.claude/rules/`, which is why the
portable content stays in the five guides.

## Branch / PR model

- Branch off `main`. Use `feat/`, `fix/`, `chore/`, `docs/` prefixes.
- Keep PRs small and focused. One logical change per PR.
- Coverage gates are **>=97%** (`packages/meshsa`) and **>=96%** (`packages/jetson_yolo_gcs`),
  enforced by each package's `pyproject.toml` `addopts`; new code should keep the suite at 100%.
  Always run the full suite — a single-file run fails the gate even when its tests pass.
- Update `CHANGELOG.md` under `## [Unreleased]` for any user-visible change.
- Run `pre-commit run -a` and `make -f tools/Makefile test lint type` locally before
  pushing (or the full gate: `make validate-pre-pr`).

### Required checks

A PR is mergeable when every `ci` workflow job is green: `test` (py3.10–3.12: ruff,
mypy, pytest with the coverage gate, build), `perception` (same for
`packages/jetson_yolo_gcs`), `governance` (hook tests, `bind_guard`, `literal_guard`,
workforce lint, skills lint, instruction-file lint, tool-pin sync, gitleaks), and
`shell` lint. Branch protection on `main` is expected to require these
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
