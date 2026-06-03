---
name: ops-deploy-base-node
description: "Use when: updating base node deployment, meshsa-base systemd service, Raspberry Pi 5 setup, mesh-up.sh, FreeTAKServer bridge install, env files, field runbooks, or ops scripts."
argument-hint: "Target node type, deployment path, service change, and validation available"
---

# Deploy or Update a Base Node

## When to Use

- Change `ops/base-service` install docs, env examples, or systemd unit.
- Change `ops/pi5-node` provisioning scripts or mesh setup.
- Document field deployment of the Meshtastic to FreeTAKServer bridge.

## Procedure

1. Read [../../../ops/AGENTS.md](../../../ops/AGENTS.md).
2. Keep service, install guide, and env example in sync.
3. Use `meshsa-base` as the installed entry point; do not reference deleted root
   scripts or old `meshsa_framework` paths.
4. Keep credentials, PSKs, host-specific callsigns, and tokens out of tracked
   files. Use placeholders in `.env.example` files.
5. Preserve graceful shutdown (`KillSignal=SIGINT`) for the asyncio bridge.
6. For Pi scripts, prefer idempotent setup steps and explicit package names.
7. Update root README deployment links if paths change.
8. State whether validation was docs-only, syntax-only, or hardware-tested.

## References

- `ops/base-service/INSTALL_base_node.md`
- `ops/base-service/base.env.example`
- `ops/base-service/meshsa-base.service`
- `ops/pi5-node/README_pi5_node.md`
- `ops/pi5-node/mesh-up.sh`
- `ops/pi5-node/setup_pi5_node.sh`