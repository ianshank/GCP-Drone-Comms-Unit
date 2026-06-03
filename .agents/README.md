# Agent Harness Index

This directory contains project-local skills for AI coding agents. The canonical
always-on guide is [../AGENTS.md](../AGENTS.md); tool-specific pointers live in
[../CLAUDE.md](../CLAUDE.md) and
[../.github/copilot-instructions.md](../.github/copilot-instructions.md).

## Skills

| Skill | Use when |
| ----- | -------- |
| [meshsa-add-transport](skills/meshsa-add-transport/SKILL.md) | Adding or changing a radio/IP/TAK transport |
| [meshsa-add-codec](skills/meshsa-add-codec/SKILL.md) | Adding or changing wire encodings |
| [meshsa-schema-version-bump](skills/meshsa-schema-version-bump/SKILL.md) | Changing the Envelope schema or compatibility window |
| [meshsa-test-conventions](skills/meshsa-test-conventions/SKILL.md) | Writing tests, fixing flaky tests, preserving coverage |
| [ops-deploy-base-node](skills/ops-deploy-base-node/SKILL.md) | Updating base-node or Pi deployment runbooks |

Keep skills short and keyword-rich. Put long references beside the skill only when
the workflow truly needs them.
