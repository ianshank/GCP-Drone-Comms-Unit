---
name: meshsa-commanding-safety
description: "Use when: touching the supervised two-way command path (Initiative C) — meshsa.command.*, flightctl/run_commander.py, arm/disarm/RTL/set_mode, COMMAND_INT/ACK, force-disarm, operator confirmation, command audit log, or arm preconditions."
argument-hint: "The command-path change and which safety control it affects"
---

# MeshSA Supervised Commanding — Safety First

This is the highest-risk subsystem in the repo: a **write path to a vehicle**. The MAVLink
plumbing is easy; the safety/auth/audit layer is the point. Never relax it to land a change.

## When to Use

- Editing anything under `packages/meshsa/src/meshsa/command/` or `flightctl/run_commander.py`.
- Adding a command to the bounded set, changing ack/retry, or the audit/confirmation/health gates.

## Non-negotiable controls (CHARTER §3 carve-out; design in initiative-c doc §4)

1. **Per-command operator confirmation.** `command/safety.py` `ConfirmationGate`: stage → explicit
   confirm → transmit. No implicit batching, no "confirm once, fire many." An unconfirmed command
   is never emitted.
2. **Command-channel authentication.** `run_commander.py` binds **loopback by default**, requires
   `MESHSA_CMD_TOKEN` (constant-time compare) and **fails closed** on a non-loopback bind without a
   token. Do not weaken this; do not document an off-loopback bind without the M2 TLS/auth layer.
3. **Append-only audit log.** `command/audit.py` `JsonlAuditLog` is fsync-durable, single-writer,
   **never drops** a record (write error propagates → fail-closed). Every stage/confirm/attempt/
   ack/retry/failure is recorded. The record shape (`AUDIT_RECORD_FIELDS = ("t","event","data")`)
   is a wire contract — changing it is a breaking change.
4. **Arm preconditions.** `command/safety.py` `arm_allowed()` + `command/health.py`
   `HeartbeatHealth`: an arm command is only offered when the health report is **fresh and OK**
   (fail-closed). Mirrors the FPV `ArmGuard` predicate.
5. **Force-disarm gate.** `MAV_CMD_COMPONENT_ARM_DISARM` param2 = `FORCE_DISARM_MAGIC` (21196)
   bypasses interlocks incl. in-flight disarm. It is **off by default** (`allow_force_disarm`),
   behind a **separate** `force_ack=True` confirmation — a normal confirm must **never** release it.
6. **Whitelist-first.** Default `allowed = {"set_mode", "rtl"}`; arm/disarm/goto are opt-in.
   `build_command()` enforces it. LLM stays read-only — no model-initiated commands, ever.

## Procedure

1. Read the design + status banner in
   [../../../docs/specs/initiative-c-commanding-design.md](../../../docs/specs/initiative-c-commanding-design.md)
   and [../../../docs/CHARTER.md](../../../docs/CHARTER.md) §3.
2. Keep stateful I/O (ack/retry loop, audit writes) in the **service/lifecycle**, not in any
   codec. Commands are a standalone service — they do **not** traverse `Router` (design §10).
3. Add adversarial tests: unconfirmed → not emitted; force needs its own confirm; arm blocked on
   stale/unhealthy; audit never-dropped under overflow (block-then-`LoggerOverflowError`).
   Fakes only — scripted fake connection, no autopilot (see `tests/test_command_*.py`).
4. Every operational value (retry count, ack timeout, report max-age, force-enable flag) is a
   config field with an explicit default — no literals.
5. Run the gates from `packages/meshsa`: `python -m pytest`, `mypy src`, `ruff check .`,
   `ruff format --check .`. Keep the safety files at 100% coverage.

## References

- `packages/meshsa/src/meshsa/command/` (safety, audit, health, lifecycle, service, commands)
- `flightctl/run_commander.py`
- `packages/meshsa/tests/test_command_*.py`
- `docs/specs/initiative-c-commanding-design.md` (§4 safety layer, §5 force gate, §10 amendment)
</content>
