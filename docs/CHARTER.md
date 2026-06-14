# Project Charter — GCP-Drone-Comms-Unit (stable long-term plan)

> **Status: STABLE / SLOW-CHANGING.** This document is the north-star that humans and AI
> agents (and sub-agents) read first to stay on track. It changes rarely and only by
> deliberate decision — not per task. Day-to-day, changeable work lives in
> [NEXTSTEPS.md](NEXTSTEPS.md); architecture detail in [C4.md](C4.md) /
> [ARCHITECTURE.md](ARCHITECTURE.md). If a task seems to require changing this charter,
> stop and raise it explicitly rather than editing it in passing.

## 1. Vision
A small, rugged, field-deployable **comms unit** that fuses **drone/flight-controller
telemetry** and a **mesh situational-awareness network** into **TAK/ATAK**, so operators
see drones, vehicles, and teammates as live tracks on one map — over whatever links are
available (LoRa, HaLow, IP, cellular/VPN), with or without internet.

## 2. Mission (what we are building)
- Ingest telemetry from **MAVLink** autopilots and **Betaflight (MSP)** flight controllers.
- Bridge a **mesh SA** network (Meshtastic/LoRa, HaLow 802.11s, IP) to **CoT**.
- Deliver **Cursor-on-Target** to ATAK clients via a TAK server (FreeTAKServer) and/or the
  ATAK multicast SA group.
- Run on constrained edge hardware (NVIDIA Jetson, Raspberry Pi) as supervised services.

## 3. Scope
**In scope:** the `meshsa` framework (transports, codecs, router/bridge), the `flightctl`
ops layer (gateway, FreeTAKServer, MAVLink proxy, simulators, deployment scripts), and the
hardware enclosures.

**Out of scope (non-goals):** flying/controlling aircraft (we are read-only on telemetry,
not a ground control station that commands vehicles — see the bounded pre-flight
arm-gating carve-out below); running the ATAK Android app on the unit (ATAK runs on
phones); becoming a general message broker; replacing the autopilot, FC firmware, or the
TAK server.

> **Carve-out (deliberate amendment — ratified by the maintainer on 2026-06-12 per §6):
> pre-flight arm-gating only.** The `meshsa.fpv` ground-side subsystem may transmit RC frames for the
> single purpose of a **pre-flight safety interlock**: `ArmGuard` gates the arm RC channel
> low until pre-flight health checks pass. Once the arm channel goes high, `ArmGuard` never
> commands or modifies any RC channel thereafter (including arm); the latch resets only when
> the operator commands the arm channel low (disarm). If health degrades after arm, clamping
> resumes only after that operator-driven disarm. This is a pre-flight interlock only — it
> **never disarms in flight** and performs **no in-flight intervention** (no auto-RTH,
> auto-land, throttle, or auto-disarm; degraded-link authority stays with the ELRS RF
> failsafe → Betaflight `failsafe_procedure`). This narrowly-scoped exception does not make
> the unit a general ground control station; everything else in this non-goal stands.

## 4. Invariants (must not drift — enforce in review)
1. **Open/closed extensibility.** New mediums and wire formats are added through
   `transport_registry` / `codec_registry`; the router, node, and models are not edited for
   a new transport/codec.
2. **Versioned, backward-compatible wire.** Every `Envelope` carries `schema_version`; peers
   accept `[MIN_COMPATIBLE_SCHEMA, SCHEMA_VERSION]`; `build_node` skips unknown transports.
   Envelope-shape changes follow the full bump ritual (version + tests + docs + CHANGELOG).
3. **Dependency injection via `Protocol`.** `Transport`/`Codec`/`Clock`/`IdFactory` are
   structural; unit tests use fakes and require no radios, sockets, or live servers.
4. **Stateful I/O lives in transports, not codecs.** Codecs are pure per-frame maps.
5. **Config-driven, no magic numbers.** Every operational value is a config field with an
   explicit default.
6. **Quality gates are non-negotiable.** `ruff`, `ruff format`, `mypy --strict`, and the
   pure-Python test suite at high coverage stay green; hardware/socket glue is the only
   `# pragma: no cover`.
7. **No secrets, no machine fingerprints in the repo.** Credentials and host-specific values
   live in `*.env`/runtime config, never committed.

## 5. Long-term roadmap (themes, not dates)
- **M1 — Telemetry→CoT MVP (done):** `mavlink_source` + `msp_source` + `telemetry` codec →
  CoT air tracks; FreeTAKServer on the unit; verified end-to-end on hardware.
- **M2 — Hardening:** TLS CoT (`:8089`) + signed ATAK data packages; auth; rate-limit/pacing
  to FTS; structured metrics export; soak/fuzz on real radios.
- **M3 — Richer tracks:** course/speed/battery/attitude as additive CoT detail; sensor
  point-of-interest and field-of-view; multiple simultaneous UAS.
- **M4 — Fleet & resilience:** multi-unit federation, store-and-forward over intermittent
  links, health/observability dashboards, OTA-style config management.
- **M5 — Packaging:** reproducible images, NVMe-root appliance build, signed releases.

## 6. How agents use this document
- Read this **before** planning a task; keep changes consistent with §3 scope and §4
  invariants.
- Put concrete, changeable to-dos in [NEXTSTEPS.md](NEXTSTEPS.md), not here.
- When a change would violate an invariant or expand scope, surface it for a human decision.
