# Long-Term Roadmap — GCP-Drone-Comms-Unit (stable trajectory)

> **Status: STABLE / SLOW-CHANGING.** This is the milestone-level *trajectory* that humans
> and AI agents (and sub-agents) read to stay on track across many tasks. It pairs with
> [CHARTER.md](CHARTER.md) (the *why / what / rules* north-star) and
> [NEXTSTEPS.md](NEXTSTEPS.md) (the *changeable near-term backlog*). Reading order for an
> agent picking up work: **CHARTER → ROADMAP → the nearest scoped `AGENTS.md` → NEXTSTEPS**.
>
> Change this file only by deliberate decision, like the charter — not per task. Put concrete,
> shifting to-dos in NEXTSTEPS, never here. If a task seems to require changing this roadmap,
> stop and raise it explicitly.

## North star (one sentence)
A small, rugged, field-deployable comms unit that fuses drone/flight-controller telemetry and
a mesh situational-awareness network into TAK/ATAK, over whatever links are available, with or
without internet — read-only by default, with **bounded, human-supervised** commanding as a
ratified extension (see CHARTER §3).

## Milestone trajectory (themes, not dates)

| Milestone | Theme | State |
| --------- | ----- | ----- |
| **M1** | Telemetry → CoT MVP | **done** |
| **M2** | Hardening & productization | **in progress** |
| **M3** | Richer tracks | planned |
| **M4** | Fleet & resilience | planned |
| **M5** | Packaging & appliance | planned |
| **C** | Supervised commanding (cross-cutting initiative) | ratified, gated on M2 |

### M1 — Telemetry → CoT MVP (done)
`mavlink_source` + `msp_source` + `crsf_source` + `telemetry`/`cot` codecs → CoT **air** tracks;
FreeTAKServer on the unit; verified end-to-end on hardware. FPV ground-side subsystem
(`meshsa.fpv`) with CRSF link health, flight logging, camera capture, and the pre-flight
`ArmGuard` interlock.

### M2 — Hardening & productization (in progress)
TLS CoT (`:8089`) + signed ATAK data packages; transport/endpoint **authentication**;
rate-limit/pacing to FTS (`FTS_COMPAT`); structured metrics export (Prometheus/JSON) with
Grafana golden-signal dashboards; soak/fuzz on real radios; reproducible builds. **Security
invariant for this milestone: no unauthenticated surface is exposed by default** (network
services bind loopback unless explicitly configured + authenticated).

### M3 — Richer tracks (planned)
Course/speed/battery/attitude as additive CoT detail (no envelope bump); sensor
point-of-interest and field-of-view CoT; multiple simultaneous UAS with stable UIDs;
MAVLink-over-ELRS consolidation; optional Remote ID → CoT ingest.

### M4 — Fleet & resilience (planned)
Multi-unit federation; store-and-forward over intermittent links (Meshtastic S&F);
health/observability dashboards; OTA-style config management.

### M5 — Packaging & appliance (planned)
Reproducible multi-arch (arm64) images; NVMe-root appliance build; signed releases;
GHCR publish on tags.

### Initiative C — Supervised two-way commanding (ratified 2026-06-16, gated on M2)
A bounded, human-supervised command path (CHARTER §3 carve-out). Whitelist-first
(`SET_MODE`/`RTL` before arm/disarm), added via `transport_registry` with no router/node
edits, `COMMAND_INT` + `COMMAND_ACK` with bounded retries, and a **mandatory** safety layer:
per-command operator confirmation, command-channel authentication, append-only audit log,
and `health_all_ok`-style preconditions. **No command code path ships before M2 hardening
lands.** Mission/waypoint autonomy, swarm, and BVLOS autonomy stay out of scope pending a
separate amendment.

## Invariants that gate every milestone
These never relax as the roadmap advances (full list in [CHARTER.md](CHARTER.md) §4):
open/closed registry extensibility; versioned backward-compatible wire; DI via `Protocol`
(tests need no hardware); pure codecs; config-driven (no magic numbers); green
`ruff`/`mypy --strict`/high-coverage gates; no secrets or host fingerprints in the repo.

## What "on track" means
A change is on-track if it (1) advances a milestone above, (2) respects every CHARTER
invariant, and (3) does not expand scope beyond CHARTER §3 (including the bounded commanding
carve-out). When a change would violate an invariant or expand scope, surface it for a human
decision rather than proceeding.
