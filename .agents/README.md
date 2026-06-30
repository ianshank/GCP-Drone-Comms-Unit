# Agent Harness Index

This directory contains project-local skills for AI coding agents. The canonical
always-on guide is [../AGENTS.md](../AGENTS.md); tool-specific pointers live in
[../CLAUDE.md](../CLAUDE.md) and
[../.github/copilot-instructions.md](../.github/copilot-instructions.md).

## Skills

| Skill | Use when |
| ----- | -------- |
| [spec-driven-change](skills/spec-driven-change/SKILL.md) | Starting any roadmap/initiative feature — author/update a spec under `docs/specs` first |
| [meshsa-add-transport](skills/meshsa-add-transport/SKILL.md) | Adding or changing a radio/IP/TAK transport |
| [meshsa-add-codec](skills/meshsa-add-codec/SKILL.md) | Adding or changing wire encodings |
| [meshsa-schema-version-bump](skills/meshsa-schema-version-bump/SKILL.md) | Changing the Envelope schema or compatibility window |
| [meshsa-commanding-safety](skills/meshsa-commanding-safety/SKILL.md) | Touching the supervised command path (Initiative C): safety/auth/audit/health, force-disarm, whitelist |
| [meshsa-observability](skills/meshsa-observability/SKILL.md) | Metrics/health export: `RouterMetrics`, `render_prometheus`, golden signals, Grafana |
| [meshsa-inference](skills/meshsa-inference/SKILL.md) | The Nemotron AI bridge: lazy aiohttp, session reuse, feedback-loop filter, env config, test mocks |
| [jetson-perception](skills/jetson-perception/SKILL.md) | `packages/jetson_yolo_gcs`: detector backends, GStreamer, `LANDING_TARGET` safety |
| [meshsa-test-conventions](skills/meshsa-test-conventions/SKILL.md) | Writing tests, fixing flaky tests, preserving coverage |
| [ops-deploy-base-node](skills/ops-deploy-base-node/SKILL.md) | Updating base-node or Pi deployment runbooks |
| [pre-pr-validator](skills/pre-pr-validator/SKILL.md) | Running the pre-PR quality gates and gap report before pushing |

Keep skills short and keyword-rich. Put long references beside the skill only when
the workflow truly needs them.
