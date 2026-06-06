# Agent Operating Guide

This is the canonical guide for AI coding agents working in this repository.
Tool-specific files such as [CLAUDE.md](CLAUDE.md) and
[.github/copilot-instructions.md](.github/copilot-instructions.md) point here to
avoid drift. When editing inside a subfolder, also read the nearest scoped
`AGENTS.md`.

**Read [docs/CHARTER.md](docs/CHARTER.md) first** — it is the stable long-term plan
(vision, scope/non-goals, and invariants that must not drift) that keeps work on track.
It changes rarely and only by deliberate decision. Put changeable, near-term to-dos in
[docs/NEXTSTEPS.md](docs/NEXTSTEPS.md), not in the charter. Architecture detail lives in
[docs/C4.md](docs/C4.md) and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Repository Map

| Path | Scope |
| ------ | ----- |
| [packages/meshsa](packages/meshsa) | Python framework, codecs, transports, tests, console script |
| [ops](ops) | Raspberry Pi 5 provisioning and base-node systemd deployment |
| [hardware](hardware) | 3D-printable hardware assets and generation scripts |
| [docs](docs) | Architecture and audit/backlog documents |
| [tools](tools) | Makefile shortcuts and runtime Dockerfile |
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

Targeted pytest runs use the same project coverage config; a single test file can
fail `--cov-fail-under=90` even when its tests pass. Use the full suite for the
final coverage gate.

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

- [.agents/skills/meshsa-add-transport/SKILL.md](.agents/skills/meshsa-add-transport/SKILL.md)
- [.agents/skills/meshsa-add-codec/SKILL.md](.agents/skills/meshsa-add-codec/SKILL.md)
- [.agents/skills/meshsa-schema-version-bump/SKILL.md](.agents/skills/meshsa-schema-version-bump/SKILL.md)
- [.agents/skills/meshsa-test-conventions/SKILL.md](.agents/skills/meshsa-test-conventions/SKILL.md)
- [.agents/skills/ops-deploy-base-node/SKILL.md](.agents/skills/ops-deploy-base-node/SKILL.md)

## Custom Agents

The focused modes in [.github/agents](.github/agents) are optional helpers for
larger tasks:

- `meshsa-framework.agent.md` for framework implementation.
- `meshsa-ops.agent.md` for deployment/runbook changes.
- `meshsa-review.agent.md` for review and risk analysis.
