# MeshSA Framework Agent Guide

This guide applies under `packages/meshsa`. Also follow the root
[../../AGENTS.md](../../AGENTS.md).

## Scope

- Source code lives in [src/meshsa](src/meshsa).
- Tests live in [tests](tests).
- The field CLI is [src/meshsa/examples/base_node.py](src/meshsa/examples/base_node.py)
  and is exposed as the `meshsa-base` console script.

## Framework Rules

- Keep transports and codecs registered by import-time factories in
  `meshsa.registry`.
- New transports should implement the `Transport` Protocol or subclass
  `transports.base.AbstractTransport` when the async inbox pattern fits.
- New codecs must encode/decode `Envelope` and enforce schema compatibility on
  decode.
- Keep operational defaults in Pydantic config models, not hidden inside router
  or transport logic.
- Tests should use fakes (`LoopbackBus`, injected connectors, `FakeClock`,
  `SeqIdFactory`) instead of live hardware or network dependencies.
- Do not loosen strict mypy to land a feature. Fix the type boundary instead.

## Common Tasks

- Adding a transport: use [../../.agents/skills/meshsa-add-transport/SKILL.md](../../.agents/skills/meshsa-add-transport/SKILL.md).
- Adding a codec: use [../../.agents/skills/meshsa-add-codec/SKILL.md](../../.agents/skills/meshsa-add-codec/SKILL.md).
- Changing the envelope schema: use [../../.agents/skills/meshsa-schema-version-bump/SKILL.md](../../.agents/skills/meshsa-schema-version-bump/SKILL.md).
- Writing tests: use [../../.agents/skills/meshsa-test-conventions/SKILL.md](../../.agents/skills/meshsa-test-conventions/SKILL.md).

## Verification

```powershell
python -m pytest
mypy src
ruff check .
ruff format --check .
python -m build
```