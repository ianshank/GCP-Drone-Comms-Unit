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
ops layer (gateway, FreeTAKServer, MAVLink proxy, simulators, deployment scripts), the
hardware enclosures, and the `jetson_yolo_gcs` on-board perception package (detection → GCS
video + precision-landing guidance — see the perception carve-out below).

**Out of scope (non-goals):** flying/controlling aircraft (we are read-only on telemetry
**by default**, not a general ground control station — see the bounded carve-outs below:
pre-flight arm-gating, and the supervised-commanding amendment); running the ATAK
Android app on the unit (ATAK runs on
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

> **Carve-out (deliberate amendment — ratified by the maintainer on 2026-06-16 per §6):
> supervised two-way commanding.** The unit MAY originate a **bounded,
> human-supervised** set of MAVLink commands to a connected vehicle, lifting the blanket
> "read-only" stance for those commands only. Constraints (all required):
> - **Bounded command set, whitelist-first.** Begin with low-risk commands (`SET_MODE`,
>   `Return-to-Launch`), then arm/disarm. Mission/waypoint autonomy, swarm, and BVLOS
>   autonomy stay out of scope until separately ratified.
> - **Added via the registry (Invariant 1).** Commanding ships as a write-capable transport
>   registered through `transport_registry` (and a command codec) — the router, node, and
>   models are not edited. Positional commands use `COMMAND_INT`; each command is confirmed
>   via `COMMAND_ACK`/`MAV_RESULT` with **bounded retries** on a missing ACK.
> - **Safety/auth/audit are mandatory, not optional.** Every command requires (a) explicit
>   per-command **operator confirmation**, (b) **command-channel authentication**, (c) an
>   **append-only audit log**, and (d) `health_all_ok`-style preconditions before arm. The
>   `MAV_CMD_COMPONENT_ARM_DISARM` **force path (param2 = 21196**, which bypasses interlocks
>   including **in-flight disarm**) is OFF by default and gated behind a separate explicit
>   confirmation.
> - **LLM stays read-only.** `meshsa.llm` issues **no** commands autonomously; any future
>   command tool requires a human confirmation in the loop.
> - **Sequenced after hardening.** No command surface ships before M2 transport auth/TLS
>   lands; an unauthenticated command surface (e.g. raw `mavlink2rest` on `:8088`) must never
>   be exposed in a deployment.
>
> This remains **bounded supervised commanding**, not a general autonomous GCS. Ratification
> authorizes the initiative under the constraints above; it does **not** flip a switch — no
> command-capable code path is enabled by default, and none ships until M2 hardening (TLS +
> transport auth) and the safety/auth/audit layer land. Mission/waypoint autonomy, swarm, and
> BVLOS autonomy remain out of scope pending a separate amendment.

> **Carve-out (deliberate amendment — ratified by the maintainer on 2026-06-20 per §6):
> on-board perception & precision-landing guidance.** A new, self-contained package
> (`jetson_yolo_gcs`) MAY run on-board **object detection** (YOLO/Hailo), **stream video** to a
> ground control station (e.g. QGroundControl), and **publish MAVLink `LANDING_TARGET`**
> precision-landing guidance to a connected autopilot. This lifts the "no on-board video / no
> detection" non-goal for that package only, and adds a narrow write path. Constraints (all
> required):
> - **Advisory only, opt-in, off by default.** `LANDING_TARGET` is *advisory* input to the
>   autopilot's own precision-landing mode. The publisher is gated behind
>   `MavlinkSettings.enable_landing_target` (default **false**) and ships disabled; it does
>   **not** arm, set modes, send RC, or otherwise fly the aircraft. Authority to act on the
>   hint stays entirely with the autopilot and the pilot.
> - **Same invariants as the rest of the repo.** Detection backends are added through a
>   registry (Invariant 1); detector/camera/stream/MAVLink seams are `Protocol`s so tests use
>   fakes and need no GPU/camera/autopilot (Invariant 3); every operational value is a config
>   field with an explicit default (Invariant 5); hardware/encoder glue is the only
>   `# pragma: no cover` and the gates stay green at high coverage (Invariant 6).
> - **Reuses, does not fork, the proven primitives.** It mirrors meshsa's logging, clock,
>   registry, and camera-source abstractions rather than introducing a parallel stack, and
>   carries no runtime dependency on `meshsa` so it remains usable as a standalone library.
>
> This narrowly-scoped exception does not make the unit a general ground control station or a
> mission/waypoint/autonomy platform; everything else in the non-goal above still stands.

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
> The detailed milestone trajectory lives in [ROADMAP.md](ROADMAP.md); the themes below are
> the summary. Keep the two aligned — milestone detail changes there, not here.

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
