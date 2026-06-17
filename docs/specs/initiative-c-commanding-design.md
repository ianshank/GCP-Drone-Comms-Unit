# Initiative C — Supervised Two-Way Commanding (Design Only)

> **Status: DESIGN / NOT IMPLEMENTED.** This is governance documentation for a
> **ratified-but-gated** initiative. It defines *how* a bounded, human-supervised
> command path would be built so that the safety layer is designed before any code
> exists — it does **not** authorize shipping code. Reading order for an agent
> picking up this area: [CHARTER.md](../CHARTER.md) §3 (supervised-commanding
> carve-out, ratified 2026-06-16) → [ROADMAP.md](../ROADMAP.md) Initiative C →
> [NEXTSTEPS.md](../NEXTSTEPS.md) "GCS commanding" → this document.

-----

> ## ⛔ GATE — READ FIRST
>
> **No command-capable code path ships before M2 hardening lands (TLS CoT `:8089`
> + transport/endpoint authentication) AND the full safety layer in §4 below is
> implemented.**
>
> Ratification ([CHARTER.md](../CHARTER.md) §3, 2026-06-16) authorized the
> *initiative under constraints*; it did **not** flip a switch. No command-capable
> code path is enabled by default, and none ships until both preconditions hold.
> An unauthenticated command surface (e.g. raw `mavlink2rest` on `:8088`) must
> **never** be exposed in a deployment ([ROADMAP.md](../ROADMAP.md) Initiative C;
> [CHARTER.md](../CHARTER.md) §3 "Sequenced after hardening").

-----

## 1. Purpose & scope of this document

This document is **design only**. It records the intended architecture, the
mandatory safety layer, and the invariant checklist for Initiative C so the
hard parts are settled before implementation begins. It ships **no code**, plans
**no code that may ship before the gate above clears**, and changes nothing in
the running system.

What Initiative C *is*: a bounded, human-supervised set of MAVLink commands to a
connected vehicle, lifting the blanket "read-only" stance for those commands only
([CHARTER.md](../CHARTER.md) §3).

What it is **not**: a general autonomous ground control station. Mission/waypoint
autonomy, swarm, and BVLOS autonomy stay out of scope pending a **separate
amendment** (§7).

-----

## 2. Registry seam — write-capable transport + command codec, zero core edits

The framework's open/closed invariant ([CHARTER.md](../CHARTER.md) §4.1) makes the
command path an *addition*, not a modification. The receive-only flight sources
(`mavlink_source`, `msp_source`, `crsf_source`) already register through
`transport_registry`; the command path is its mirror image.

**The seam already exists.** `Router.publish` and `Router._pump` both emit through:

```python
await transport.send(self._codec_for(transport).encode(envelope))
```

(`packages/meshsa/src/meshsa/router.py`, lines 80 and 109). The `Transport`
Protocol already declares `async def send(self, data: bytes)` and the `Codec`
Protocol already declares `encode`/`decode`
(`packages/meshsa/src/meshsa/protocols.py`). So a write-capable transport plus a
command codec slot in with **no edits to `router.py`, `node.py`, or `models.py`**.

Design (not built):

- **`mavlink_sink` transport** — a new write-capable transport registered via
  `@transport_registry.register("mavlink_sink")`. Today
  `PollingSourceTransport.send` is a deliberate **no-op**
  (`packages/meshsa/src/meshsa/transports/polling_source.py`, bottom: "Receive-only
  source: nothing to transmit back toward the aircraft"). That no-op is the natural
  seam: the sink **implements `send`** to encode and emit a MAVLink command toward
  the vehicle (via pymavlink or a hardened `mavlink2rest` client), where the source
  left it empty. The same dependency-injection + `# pragma: no cover` hardware-factory
  pattern as `mavlink_source` applies (`connection`/`connection_factory` injected;
  only the real link builder is uncovered).
- **Command codec** — registered via `codec_registry`, mapping a command `Envelope`
  to the on-wire MAVLink command frame (`encode`) and the `COMMAND_ACK` back to a
  result (`decode`). It stays a **pure per-frame map** ([CHARTER.md](../CHARTER.md)
  §4.4): all stateful I/O (retries, ack-matching loop) lives in the transport, not
  the codec.

Because the seam is the existing `transport.send(codec.encode(envelope))` line,
the core router/node/models are untouched — the addition is "config + factory,"
exactly as for every other transport.

-----

## 3. Command semantics

- **Positional commands use `COMMAND_INT`** (lat/lon as scaled integers; the
  frame-of-reference and integer scaling avoid the float-precision pitfalls of
  `COMMAND_LONG` for geographic params).
- **Every command is confirmed** via `COMMAND_ACK` / `MAV_RESULT`, with **bounded
  retries** on a missing ACK (retry count + timeout are config fields, §8). After
  the bound is exhausted, the command **fails closed** and is recorded as failed in
  the audit log (§4c).
- **Acks signal intent, not completion.** A `MAV_RESULT_ACCEPTED` means the
  autopilot accepted the command for execution — not that the maneuver finished.
  The design must never treat an ACK as proof of physical state; completion (e.g.
  "did it actually RTL") is inferred from subsequent telemetry, not the ACK.

-----

## 4. The MANDATORY safety layer (this is the real work)

The MAVLink plumbing in §2–§3 is the easy part. The following four controls are
**required, not optional** ([CHARTER.md](../CHARTER.md) §3). A command path that
omits any of them does not satisfy the carve-out and must not ship.

### 4a. Per-command operator confirmation gate

Every command requires an **explicit, per-command** human confirmation before the
transport emits it — no implicit batching, no "confirm once, fire many." The gate
sits in front of `mavlink_sink.send`; an unconfirmed command is never transmitted.
The confirmation is itself an audited event (§4c).

### 4b. Command-channel authentication — **gated on M2**

The command channel must be authenticated. This is **explicitly gated on the M2
TLS/auth work** (TLS CoT `:8089` + transport/endpoint authentication;
[ROADMAP.md](../ROADMAP.md) M2). Until that hardening lands, there is no
authenticated channel to carry commands, so by construction no command path can
ship (this is the gate at the top of the document, restated as an architectural
dependency). The insecure-by-default building blocks (`mavlink2rest`,
FreeTAKServer, the TAK transports) are unauthenticated/plaintext out of the box
and must have the auth/TLS layer in front of them first
([NEXTSTEPS.md](../NEXTSTEPS.md) "Known risks").

### 4c. Append-only audit log — built on the `FlightLogger.record_event` pattern

Every command attempt, confirmation, ACK/result, retry, and failure is written to
an **append-only audit log**, designed on the **never-dropped** primitive that
already exists: `FlightLogger.record_event`
(`packages/meshsa/src/meshsa/fpv/flight_logger.py`). That method is the right model
because:

- It is **durable, not lossy.** Unlike `record_rc`/`record_telemetry`
  (drop-and-count on overflow), `record_event` **blocks the caller** up to a
  timeout and **raises `LoggerOverflowError`** rather than silently dropping —
  audit records are never lost.
- It is **single-writer-thread**, append-only JSONL (a truncated final line is
  recoverable after a crash), with a versioned manifest.
- It carries the **blocking-path contract** the audit log needs: because it can
  block, it must be called from a sync/tool context or an executor, **never
  directly on the asyncio loop thread**. The command confirmation/emit path is a
  natural sync/tool context, so this fits.

The audit log is a design analogue of (not a literal reuse of) `record_event`:
same never-dropped, append-only, single-writer discipline applied to the command
channel.

### 4d. `health_all_ok` / ArmGuard-style preconditions before arm

Arming requires **fresh, healthy** preconditions, mirroring the pre-flight
interlock concept already proven in `ArmGuard`
(`packages/meshsa/src/meshsa/fpv/arm_guard.py`). `ArmGuard` gates the
**disarmed → armed** transition on a `HealthReport` that is both fresher than a
max-age bound and `arm_permitted` (`HealthState.OK`); otherwise it blocks and emits
an `arm_blocked` event. The commanding arm precondition follows the same shape: a
`health_all_ok`-style check (fresh + OK) must pass before an arm command is even
offered for confirmation. (Note the existing `ArmGuard` threading contract docstring
already anticipates Initiative C: it flags adding a `Lock` + concurrent test when a
live monitor thread and a command/RC loop are wired separately.)

-----

## 5. Explicit gate on force-disarm (`param2 = 21196`)

`MAV_CMD_COMPONENT_ARM_DISARM` with **`param2 = 21196`** is a **force** path: it
**bypasses interlocks, including in-flight disarm** (a forced in-flight disarm cuts
motors and drops the aircraft). Therefore:

- It is **OFF by default**.
- It sits **behind a separate, explicit confirmation** that is **distinct from**
  the normal arm/disarm confirmation (§4a) — a normal-arm confirmation must never
  satisfy the force path.
- Whether force-disarm is even *available* is a config flag (§8), off by default.

This is the single most dangerous command in the bounded set; the design treats it
as a deliberate, separately-gated exception, never a default capability.

-----

## 6. `meshsa.llm` stays read-only

`meshsa.llm` issues **no** commands autonomously — no model-initiated command
issuance, ever. Any *future* command tool exposed to the LLM must be gated behind
an **explicit human confirmation in the loop** (the §4a gate); the model may
*propose*, a human *confirms*, and only then does the transport emit. (Note the
prior hardening already restored the M2 security posture for `meshsa.llm`: loopback
default bind + bearer token, fail-closed on a non-loopback bind without a token —
[NEXTSTEPS.md](../NEXTSTEPS.md) code-quality backlog. That fix was the gate on this
initiative.)

-----

## 7. Whitelist-first ordering & out-of-scope autonomy

- **Whitelist-first.** The bounded set is introduced in risk order: **`SET_MODE`
  and `RTL` before arm/disarm**. Low-risk, recoverable commands first; arm/disarm
  only after the safety layer is proven on the safer commands.
- **Out of scope (pending a separate amendment):** mission/waypoint autonomy,
  swarm, and BVLOS autonomy. These do **not** become in-scope by virtue of this
  document or the §3 ratification; they require their own ratified amendment
  ([CHARTER.md](../CHARTER.md) §6 process).

-----

## 8. Invariant checklist (the design preserves all of these)

| # | Invariant ([CHARTER.md](../CHARTER.md) §4) | How Initiative C's design preserves it |
|---|---------------------------------------------|----------------------------------------|
| 1 | **Open/closed registry** | `mavlink_sink` + command codec register via `transport_registry` / `codec_registry`; `router.py`/`node.py`/`models.py` are not edited (the seam is the existing `transport.send(codec.encode(envelope))` line, §2). |
| 2 | **Versioned, backward-compatible wire** | The command codec's `Envelope` carries `schema_version`; **additive payload keys do not bump** it. A command-envelope *shape* change follows the full bump ritual (version + tests + docs + CHANGELOG). |
| 3 | **DI via `Protocol`** | The command transport/codec are structural `Transport`/`Codec` implementations, injected and **testable hardware-free with fakes** (no radios/sockets/live autopilot), exactly as `mavlink_source` is tested today. |
| 4 | **Stateful I/O in transports, not codecs** | Retry loop, ACK-matching, and audit writes live in `mavlink_sink`; the command codec stays a pure per-frame map. |
| 5 | **Config-driven, no magic numbers** | The **whitelist, retry count, ack timeout, force-disarm enable flag**, health max-age, and confirmation policy are all config fields with explicit defaults. |
| 6 | **Quality gates** | `ruff` / `ruff format` / `mypy --strict` + the pure-Python suite stay green; only the real link builder is `# pragma: no cover` glue. |
| 7 | **No secrets / fingerprints in the repo** | Command-channel credentials are **deploy-time** (`*.env`/runtime config), never committed. |

-----

## 9. Test strategy when implementation begins (out of scope now)

When (and only when) the gate clears and implementation begins, tests are
**fakes-only**, mirroring `tests/test_mavlink_source.py` (a scripted fake
connection, no hardware). They would assert, at minimum:

- **`COMMAND_INT` encoding** — the command codec produces the expected frame
  (lat/lon scaling, frame-of-reference, params) for each whitelisted command.
- **ACK / retry behavior** — accepted on `MAV_RESULT_ACCEPTED`; **bounded retries**
  on a missing ACK; **fail-closed** after the bound, recorded as failed.
- **Confirmation gate** — an unconfirmed command is never emitted; force-disarm
  (`param2 = 21196`) requires its **separate** confirmation and is off by default.
- **Audit append** — every attempt/confirmation/result is appended and **never
  dropped** (the `record_event` block-then-raise contract holds under overflow).

These tests are described here for completeness only; **nothing is implemented and
nothing ships before the gate at the top of this document clears.**
