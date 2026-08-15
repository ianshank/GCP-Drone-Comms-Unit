---
name: config-literal-sweep
description: "Use when: adding or reviewing a service default (port, host, queue/backoff, MAVLink endpoint), running the literal_guard checker, or deciding whether a literal needs a defaults.py constant vs a governance exception."
argument-hint: "Diff or module to sweep for re-typed service literals"
---

# Config Literal Sweep

## When to Use

- A diff introduces a numeric/string default for a port, bind/connect host,
  queue size, backoff schedule, or MAVLink endpoint.
- `python tools/claude_hooks/literal_guard.py` reports a violation.
- Periodic sweeps by the `config-guardian` roster agent.

## Relationship

Extends `pre-pr-validator` (which runs the checker as a gate) and is the
mechanical loop behind the `.claude/agents/config-guardian.md` roster mandate.

## Procedure (deterministic loop)

1. **Run the checker** from the repo root:
   `python tools/claude_hooks/literal_guard.py` — findings print as
   `path:line: [rule] message` (rules: `ports`, `hosts`, `magics`, `endpoints`).
2. **For each finding, prefer adoption over waiver**:
   - The value already has a constant in `packages/meshsa/src/meshsa/defaults.py`
     → import and use it (`PORT_*`, `DEFAULT_QUEUE_MAXSIZE`, backoff triple,
     `DEFAULT_MAVLINK_ENDPOINT`).
   - Host defaults: `DEFAULT_LOOPBACK_HOST` for a **listener bind**,
     `DEFAULT_LOCAL_TARGET_HOST` for an **outbound connect target** — never merge
     the two (binds are guarded fail-closed by `netauth.validate_bind`; egress is
     not, so a shared constant would let one edit silently redirect traffic).
   - A genuinely new operational value → add a constant to `defaults.py` **and**
     a pinned-literal assert in `packages/meshsa/tests/test_defaults.py`; new
     ports also get a port-table row (uniqueness is reflection-tested).
3. **Waive only with a rationale**: if adoption is impossible (frozen command
   path, separate distribution, sim tooling), add a
   `{path, rule, rationale}` entry under `literal_guard:` in
   `.claude/governance.yaml`. Extend the loader model in
   `tools/claude_hooks/governance.py` FIRST if the schema changes — the
   scope-freeze hook fails open on config it cannot validate.
4. **Rerun to zero**: the checker must exit 0 with findings limited to declared
   exceptions ("clean (N excepted)"). Then run the pinned-value tests:
   `cd packages/meshsa && python -m pytest tests/test_defaults.py -q --no-cov`.
5. **Value changes are never part of a sweep**: changing a pinned default is an
   operator-visible change — CHANGELOG + ops docs + `docs/AUDIT_M2_AUTH.md` row
   update in the same commit (T-1.4 precedent), and the pin test updated last.
