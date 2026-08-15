# Agent Operating Guide

This is the canonical guide for AI coding agents working in this repository.
Tool-specific files such as [CLAUDE.md](CLAUDE.md) and
[.github/copilot-instructions.md](.github/copilot-instructions.md) point here to
avoid drift. When editing inside a subfolder, also read the nearest scoped
`AGENTS.md`.

**Reading order to stay on track: [docs/CHARTER.md](docs/CHARTER.md) →
[docs/ROADMAP.md](docs/ROADMAP.md) → the nearest scoped `AGENTS.md` →
[docs/NEXTSTEPS.md](docs/NEXTSTEPS.md) → [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md)
→ [docs/LOCAL_TESTING_PLAN.md](docs/LOCAL_TESTING_PLAN.md) → the relevant [docs/specs/](docs/specs/) spec.** CHARTER is the stable scope/non-goals +
invariants that must not drift; ROADMAP is the stable milestone trajectory. Both change rarely
and only by deliberate decision — put changeable, near-term to-dos in NEXTSTEPS, not in either.
The IMPLEMENTATION_PLAN sequences *how* the remaining work lands (spec-driven); every
roadmap/initiative feature gets a committed spec under `docs/specs/` before code (see
[docs/specs/README.md](docs/specs/README.md)). Architecture detail lives in
[docs/C4.md](docs/C4.md) and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Test taxonomy & local plan live in [docs/LOCAL_TESTING_PLAN.md](docs/LOCAL_TESTING_PLAN.md).
## Repository Map

| Path | Scope |
| ------ | ----- |
| [packages/meshsa](packages/meshsa) | Python framework, codecs, transports, tests, console script |
| [ops](ops) | Raspberry Pi 5 provisioning and base-node systemd deployment |
| [hardware](hardware) | 3D-printable hardware assets and generation scripts |
| [docs](docs) | Stable plan ([CHARTER](docs/CHARTER.md), [ROADMAP](docs/ROADMAP.md)), architecture (C4/ARCHITECTURE), and audit/backlog documents |
| [tools](tools) | Makefile shortcuts, runtime Dockerfile, governance hooks (`claude_hooks/`) and the repo checkers (`bind_guard`, `literal_guard`, `check_tool_pins`, `check_task_sync`, `validate_workforce`, `validate_skills`) with their tests |
| [.agents/skills](.agents/skills) | On-demand playbooks for repeatable agent workflows |
| [.github/agents](.github/agents) | Focused custom agent modes |
| [archive](archive) | Historical ZIP snapshots; treat as read-only |

## Commands

Run package commands from the repository root unless the command explicitly uses
package-local context.

| Goal | Command |
| ---- | ------- |
| Install dev dependencies | `python -m pip install -e "packages/meshsa[dev,meshtastic]"` |
| Test | `cd packages/meshsa && python -m pytest` |
| Lint | `ruff check packages/meshsa` |
| Format check | `ruff format --check packages/meshsa` |
| Type-check | `cd packages/meshsa && mypy src` |
| Build package | `cd packages/meshsa && python -m build` |
| Makefile equivalent | `make -f tools/Makefile test lint type build` |
| Both packages | `make -f tools/Makefile test-all lint-all type-all` (adds `packages/jetson_yolo_gcs`) |
| Governance checkers | `make -f tools/Makefile checkers` (`bind_guard`, `literal_guard`, `check_tool_pins`, `check_task_sync`, `validate_workforce`, `validate_skills`) |
| Full pre-PR gate (TS + Python + governance) | `make validate-pre-pr` (repo-root Makefile; wraps `scripts/validate-pre-pr.sh`) |

Targeted pytest runs use the same project coverage config; a single test file can
fail `--cov-fail-under=97` even when its tests pass. Use the full suite for the
final coverage gate. `tools/Makefile`'s targets are a convenience wrapper around
individual gates, not a CI-equivalent single command — CI additionally runs across
Python 3.10–3.12, `flightctl/`+`deliverables/` lint/type-check, and the shell-lint job
(see `.github/workflows/ci.yml`).

## Engineering Rules

- Keep changes scoped. Do not reorganize folders, rewrite docs, or reformat
  unrelated files as part of feature work.
- Preserve the `src` layout under `packages/meshsa`.
- Add transports and codecs through `transport_registry` and `codec_registry`.
  Avoid editing router or node code for a new medium unless the shared contract
  truly changes.
- Keep I/O behind `Protocol` types (`Transport`, `Codec`, `Clock`, `IdFactory`)
  and injectable collaborators. Unit tests should not require radios, sockets, or
  live TAK servers.
- Every wire envelope uses `schema_version`. Envelope shape changes must update
  `meshsa.version`, tests, docs, and `CHANGELOG.md`.
- `build_node()` intentionally skips unknown transport types for forward-compatible
  config loading. Do not replace that with a hard failure.
- Use the `compact` codec for Meshtastic/LoRa examples; JSON PLIs are too large
  for reliable single-packet LoRa transport.
- Do not hand-edit generated or binary artifacts (`*.stl`, screenshots, ZIPs).
  Change generator scripts or source docs, then regenerate.
- Never commit secrets. Keep credentials and radio keys in environment files that
  are examples only, not real deployment values.

## Verification Expectations

For Python framework changes, run:

```powershell
cd packages/meshsa
python -m pytest
mypy src
ruff check .
ruff format --check .
python -m build
```

For docs-only or ops-only changes, run the relevant subset and explain what was
not run. CI should keep mypy required, not advisory.

## Agent Skills

Use these playbooks when the task matches their trigger words:

- [.agents/skills/spec-driven-change/SKILL.md](.agents/skills/spec-driven-change/SKILL.md)
- [.agents/skills/meshsa-add-transport/SKILL.md](.agents/skills/meshsa-add-transport/SKILL.md)
- [.agents/skills/meshsa-add-codec/SKILL.md](.agents/skills/meshsa-add-codec/SKILL.md)
- [.agents/skills/meshsa-schema-version-bump/SKILL.md](.agents/skills/meshsa-schema-version-bump/SKILL.md)
- [.agents/skills/meshsa-commanding-safety/SKILL.md](.agents/skills/meshsa-commanding-safety/SKILL.md)
- [.agents/skills/meshsa-observability/SKILL.md](.agents/skills/meshsa-observability/SKILL.md)
- [.agents/skills/meshsa-inference/SKILL.md](.agents/skills/meshsa-inference/SKILL.md)
- [.agents/skills/jetson-perception/SKILL.md](.agents/skills/jetson-perception/SKILL.md)
- [.agents/skills/meshsa-test-conventions/SKILL.md](.agents/skills/meshsa-test-conventions/SKILL.md)
- [.agents/skills/ops-deploy-base-node/SKILL.md](.agents/skills/ops-deploy-base-node/SKILL.md)
- [.agents/skills/pre-pr-validator/SKILL.md](.agents/skills/pre-pr-validator/SKILL.md)
- [.agents/skills/config-literal-sweep/SKILL.md](.agents/skills/config-literal-sweep/SKILL.md)

## Custom Agents

The focused modes in [.github/agents](.github/agents) are optional helpers for
larger tasks:

- `meshsa-framework.agent.md` for framework implementation.
- `meshsa-perception.agent.md` for `jetson_yolo_gcs` perception changes.
- `meshsa-commanding.agent.md` for the supervised command path (safety layer foregrounded).
- `meshsa-ops.agent.md` for deployment/runbook changes.
- `meshsa-review.agent.md` for review and risk analysis.

## Subagent roster (collaborate by default)

The M2-hardening roster in [.claude/agents](.claude/agents) delegates
proactively — do not work a multi-part task solo when a roster mandate fits.
Each entry declares its relationship to the skills/agents above
(`tools/validate_workforce.py` enforces the format). Binding rule: the
**security-reviewer** agent reviews every diff touching `packages/` or any
transport *before* a PR is opened. Mechanical governance backs this up:
`.claude/governance.yaml` drives the scope-freeze PreToolUse hook and the
`bind_guard` CI check (`tools/claude_hooks/`); the Initiative-C command path
stays frozen while `c_gate_met` is false. Change bundles live under
`openspec/changes/` (additive to `docs/specs/`, which stays authoritative for
initiative specs).
