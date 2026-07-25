# Spec Delta: m2-bind-safety

## ADDED Requirements

### Requirement: Fail-Closed Bind on Every Network Surface
Every network-facing surface SHALL refuse to bind a non-loopback address
without a non-empty authentication credential, unless it is listed as a
reviewed exception in `.claude/governance.yaml` with a stated rationale.
Exceptions remain flagged in `docs/AUDIT_M2_AUTH.md` as live gaps (the TAK
multicast precedent), not waived.

#### Scenario: UDP detection ingest bound to a routable address
- **WHEN** `DetectionIngestTransport` is configured to bind other than
  loopback and no token is set
- **THEN** construction fails closed with an error naming the surface and the
  remedy (set a `token` transport option, or bind loopback)

#### Scenario: Commander bound with an empty token
- **WHEN** the commander is asked to bind other than loopback and the token is
  the empty string
- **THEN** startup fails closed (an empty credential is no credential)

#### Scenario: Unauthenticated video egress enabled by default
- **WHEN** the Jetson `StreamSettings` default configuration is loaded
- **THEN** `enabled` is `False`; enabling requires explicit operator config
  (`STREAM_ENABLED=true`), and activation emits exactly one WARNING naming the
  destination host and port

### Requirement: Single Bind-Guard Primitive
`meshsa.netauth.validate_bind` SHALL be the only bind-guard implementation.
The `bind-guard` CI check SHALL fail when a scanned file creates a network
listener without importing and calling `validate_bind` (re-exports accepted)
and without a declared exception, or when a `def validate_bind` outside
`meshsa.netauth` does not demonstrably delegate to the canonical primitive.

#### Scenario: New listener without a bind guard
- **WHEN** a new aiohttp listener or datagram endpoint is added with no
  `validate_bind` import-and-call and no declared exception
- **THEN** the `governance` CI job fails, naming the file, line, and trigger

#### Scenario: Re-implemented bind guard
- **WHEN** a diff defines `validate_bind` outside `meshsa.netauth` whose body
  does not call the canonical imported symbol
- **THEN** the `governance` CI job fails, citing the single-primitive rule

#### Scenario: Delegating adapter
- **WHEN** a module defines `validate_bind` that imports the canonical symbol
  (any alias, absolute or relative import resolving to `netauth`) and calls it
  in its body (e.g. `llm/server.py`, `run_commander.py`)
- **THEN** the check passes — adapters are how entry points keep their own
  operator-facing error types

### Requirement: Transport Auth Seam
`meshsa.netauth` SHALL expose a `TransportAuthPolicy` protocol (bind
validation + request authorisation) with a default implementation backed by
the audited primitives, so non-HTTP surfaces have a defined place to plug
datagram signing later. The seam SHALL NOT be presented as closing the
transport-wide auth gap; `AUDIT_M2_AUTH.md` keeps the gap recorded until an
implementation lands.

#### Scenario: Seam conformance
- **WHEN** `NetAuthPolicy` (or a future signing policy) is checked against the
  protocol
- **THEN** it satisfies `TransportAuthPolicy` and its `validate_bind` fails
  closed exactly like the module primitive
