# Operations Agent Guide

This guide applies under `ops`. Also follow the root [../AGENTS.md](../AGENTS.md).

## Scope

- [base-service](base-service) contains the base-node systemd unit, environment
  example, and install guide.
- [pi5-node](pi5-node) contains Raspberry Pi 5 provisioning scripts and mesh setup
  notes.

## Traps

- **`SIGINT` is the systemd `KillSignal`**, set in
  [base-service/meshsa-base.service](base-service/meshsa-base.service) with a
  10-second `TimeoutStopSec`. It is not the default (`SIGTERM`) — the node installs an
  asyncio handler for it so transports close cleanly. Changing the signal, or adding a
  handler that swallows it, turns every stop into a 10-second timeout and a kill.
- **Only `*.example` env files are tracked here.** `base.env.example` and
  `99-meshsa-serial.rules.example` are templates; the real files are deployed, never
  committed. Adding a non-example env file puts real callsigns and keys in git history.
- **Three binary assets under `pi5-node/` are byte-identical copies of
  `hardware/usernode-stls/`** — `pi5_node_base.stl`, `pi5_node_lid.stl`,
  `pi5_node_enclosure.png`. Regenerate in `hardware/`, then copy here; updating one
  side only leaves the other silently stale.

## Rules

- Keep scripts idempotent where practical. Re-running setup should not corrupt a
  node — why: provisioning is retried after partial failures on hardware that is
  often only reachable once.
- Do not store real callsigns, keys, hostnames, or credentials in tracked env files.
  Use examples with placeholder values — why: a committed key cannot be rotated
  quietly, and this repo's nodes are field-deployed — control: `gitleaks`, in CI and
  in `.pre-commit-config.yaml`.
- Keep systemd service changes aligned with the install guide and the console script
  name `meshsa-base` — why: the unit's `ExecStart` and the guide are the only two
  places the entry point is written down, and nothing checks that they agree.
- Preserve graceful shutdown behavior for asyncio services (`SIGINT` is used so the
  node can stop transports cleanly) — why: `KillSignal=SIGINT` in the unit file
  depends on it; without the handler, stop waits out `TimeoutStopSec` and is killed.
- Shell changes should be POSIX-compatible for target Linux nodes unless a file is
  explicitly Windows-only — why: these run unattended on field hardware that is often
  reachable only once, so a shell incompatibility costs a site visit rather than a
  re-run — control: the CI `shell lint` job runs `bash -n` and
  `shellcheck -x --severity=warning` over every tracked `*.sh`.

## Common Tasks

- Base-node deployment or Pi provisioning: use
  [../.agents/skills/ops-deploy-base-node/SKILL.md](../.agents/skills/ops-deploy-base-node/SKILL.md).

## Verification

- For docs-only changes, proofread command paths and service names.
- For script changes, run the safest available syntax check locally and state if
  target hardware validation was not possible.
