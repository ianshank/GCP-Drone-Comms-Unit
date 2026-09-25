---
paths:
  - "packages/meshsa/src/**/*.py"
---

# meshsa framework source

Fires when a framework source file is opened. The package guide
[packages/meshsa/AGENTS.md](packages/meshsa/AGENTS.md) carries the same invariants at
session scope; this file exists so they arrive when you are actually in the code.

## Rules

- Register transports and codecs with the import-time decorators in `meshsa.registry`;
  never move registration to call time — why: registration is a side effect of import,
  so "which transports exist" would start depending on call order, and the failure
  reads as a config typo rather than a missing import.
- Subclass `transports.base.AbstractTransport`, or one of the receive-only bases, or
  define `send` yourself — why: `AbstractTransport.send` is an `@abc.abstractmethod`,
  so a class doing none of these cannot be instantiated at all (`TypeError` at
  construction, not a runtime error at first use).
- Leave `build_node()`'s skip of unknown transport types in place — why: a config
  naming a transport an older node lacks must degrade to "that link is absent", never
  to "this node will not start", because nodes are updated one at a time in the field.
- Do not change `netauth.validate_bind`'s `not token` guard to `token is None` — why:
  the commander's former local guard used `token is None`, so an empty-string token
  passed when called directly; `not token` is the fix, not a sloppy truthiness check
  — control: `bind_guard` (`tools/claude_hooks/bind_guard.py`) and the row table in
  `docs/AUDIT_M2_AUTH.md`.
- Put new operator-tunable values in a Pydantic config model — why: field nodes are
  reconfigured by environment, never by edit-and-redeploy, so a literal buried in logic
  is unreachable once deployed — control: `literal_guard`, which enforces four literal
  classes (`ports`, `hosts`, `magics`, `endpoints`) over
  `packages/**/src/**/*.py`; six declared waivers exist repo-wide.
- Keep `Router`'s `schema_mismatch` counter distinct from `dropped_undecodable` — why:
  it is the only signal separating a version skew from a corrupt frame, and a mixed
  version mesh is the normal case here.
- Treat `meshsa/command/**` as frozen — do not add, enable, or widen a command
  emission path — why: the M2 charter gate is unmet and only a maintainer flips
  `c_gate_met` — control: the `scope_freeze` PreToolUse hook write-denies it while
  `.claude/governance.yaml` has `c_gate_met: false`; delegate to the
  **charter-gate-keeper** subagent.
- Keep the command ACK policy fail-closed and the audit `fsync` off the asyncio loop
  thread — why: an ACK that fails open would let an unacknowledged command look
  delivered, and a blocking `fsync` on the loop stalls every other transport
  — control: `run_in_executor` at the call site in `flightctl/run_commander.py`.
- Do not add a mutating route to the operator console beyond the one that exists — why:
  invariant I-2 makes the console read-only; `POST /api/chat` is the single permitted
  mutating *method*, and it mutates nothing — control:
  `packages/meshsa/tests/test_ui_app.py` asserts the whole route table and ends
  `assert mutating == ["POST"]`.
- Keep the console's snapshot pump single-threaded — no locks, no background threads
  — why: the absence of concurrency is what makes the snapshot consistent without
  locking; adding a thread silently reintroduces the need for both.
- Do not make `import meshsa.fpv` require the `[fpv]` extra — why: the package must
  import on a node that has no `pyserial`/`pyarrow`; those import lazily inside
  functions for exactly this reason.
- Leave the CRSF byte-order asymmetry alone: CRC8/DVB-S2 (poly `0xD5`) covers
  `[type] + payload` only, telemetry payloads are big-endian, RC channels are LSB-first
  11-bit — why: the two orders are genuinely opposite in the wire protocol, so
  "fixing" the inconsistency corrupts one of them.
- Keep every LLM tool read-only, and keep `_is_ai_insight` on the inference path — why:
  the tool surface is reachable from model output, and `_is_ai_insight` is what stops
  one node's insight from feeding another's in a loop — control: the tool dispatcher
  exposes no write path; review is what keeps it that way — advisory.
