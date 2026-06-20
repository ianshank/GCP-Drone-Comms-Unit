# Operations Agent Guide

This guide applies under `ops`. Also follow the root [../AGENTS.md](../AGENTS.md).

## Scope

- [base-service](base-service) contains the base-node systemd unit, environment
  example, and install guide.
- [pi5-node](pi5-node) contains Raspberry Pi 5 provisioning scripts and mesh setup
  notes.

## Rules

- Keep scripts idempotent where practical. Re-running setup should not corrupt a
  node.
- Do not store real callsigns, keys, hostnames, or credentials in tracked env
  files. Use examples with placeholder values.
- Keep systemd service changes aligned with the install guide and the console
  script name `meshsa-base`.
- Preserve graceful shutdown behavior for asyncio services (`SIGINT` is used so
  the node can stop transports cleanly).
- Shell changes should be POSIX-compatible for target Linux nodes unless a file is
  explicitly Windows-only.

## Common Tasks

- Base-node deployment or Pi provisioning: use
  [../.agents/skills/ops-deploy-base-node/SKILL.md](../.agents/skills/ops-deploy-base-node/SKILL.md).

## Verification

- For docs-only changes, proofread command paths and service names.
- For script changes, run the safest available syntax check locally and state if
  target hardware validation was not possible.