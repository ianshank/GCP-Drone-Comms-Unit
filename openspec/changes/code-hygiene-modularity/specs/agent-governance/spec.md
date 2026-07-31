# Spec Delta: agent-governance

## ADDED Requirements

### Requirement: Denied Commands Are Audited
Every command rejected by `stage` or `confirm` — whether unknown, disallowed by
configuration, or blocked by the force-disarm interlock — SHALL append a `command_denied`
record to the audit log, naming the error type and the command, before the error propagates
to the caller. Today only successes and `arm_blocked` are recorded; a rejected confirmation
or a probe against the authenticated endpoint currently leaves no trace.

#### Scenario: Unknown command staged
- **WHEN** `stage` is called with a command name outside the allowed set
- **THEN** `UnknownCommandError` propagates to the caller **and** a `command_denied` record
  naming `UnknownCommandError` and the attempted command has already been appended

#### Scenario: Force-disarm confirmed without force acknowledgement
- **WHEN** `confirm` is called for a staged force-disarm without the required force
  acknowledgement
- **THEN** `ForceConfirmationRequired` propagates **and** a `command_denied` record is
  appended before it does

### Requirement: Confirmation Is Unforgeable and Bounded
A `CommandSpec` SHALL NOT reach `CommandSender.execute` unless it was returned by
`ConfirmationGate.confirm` as a gate-stamped `ConfirmedCommand`. A staged command SHALL
expire after a configurable `confirmation_ttl_s` and SHALL be rejected if confirmed after
that window; the set of staged commands SHALL NOT exceed a configurable `pending_cap`; and
every command — not only `arm` — SHALL have its interlock conditions re-checked at
confirmation time, not only at staging time.

#### Scenario: Execute called with an unconfirmed spec
- **WHEN** code attempts to call `CommandSender.execute` with a bare `CommandSpec` that did
  not pass through `ConfirmationGate.confirm`
- **THEN** the call is a type error at the call site — `execute`'s parameter type accepts
  only `ConfirmedCommand`

#### Scenario: Confirmation arrives after the TTL
- **WHEN** a command is staged and then confirmed after `confirmation_ttl_s` has elapsed
- **THEN** confirmation is rejected and the stale entry is removed from `_pending`

#### Scenario: Pending set is full
- **WHEN** `_pending` already holds `pending_cap` entries and a new command is staged
- **THEN** staging is rejected rather than growing the set unbounded

#### Scenario: A non-arm command's interlock degrades between staging and confirmation
- **WHEN** a `Return-to-Launch` command is staged while conditions are healthy, and health
  degrades before it is confirmed
- **THEN** confirmation re-runs the interlock check and rejects the command, not only `arm`

## Implementation notes (declared interpretations)

1. None of the three hardening requirements above enable commanding. `governance.c_gate_met`
   stays `false` throughout this change; no console-script or systemd entry point for the
   command surface ships. These requirements strengthen the gate the way
   `gcp-drone-m2-agent-hardening` built it — before any future gate-clearance decision, not
   as part of one.
2. `confirmation_ttl_s` defaults to `60.0` seconds and `pending_cap` defaults to `8`, both as
   `CommanderSettings` fields (CHARTER §4 Invariant 5 — no bare literals); a maintainer may
   retune both per deployment.
3. `command/mavlink_link.py` and `command/mavlink_pump.py` keep their currently-different
   ACK error-handling policies (propagate vs. swallow-and-log) after adopting the shared
   `Ack.from_message` constructor — the divergence is a deliberate reflection of a
   synchronous bounded-retry caller versus a reader-thread that must survive a malformed
   frame, not an inconsistency to remove.
