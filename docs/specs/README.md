# Specifications Index

> **Spec-driven development is the rule here.** Every roadmap/initiative feature gets a
> committed spec in this directory **before** code lands, and the code cites the spec by
> section number in its docstrings (the FPV subsystem and Initiative C already do this). A
> feature without a spec does not merge.

Reading order for an agent picking up work:
**[../CHARTER.md](../CHARTER.md) → [../ROADMAP.md](../ROADMAP.md) → the nearest scoped
`AGENTS.md` → [../NEXTSTEPS.md](../NEXTSTEPS.md) → [../IMPLEMENTATION_PLAN.md](../IMPLEMENTATION_PLAN.md)
→ the relevant spec below.**

## How to add a spec

1. Copy [TEMPLATE.md](TEMPLATE.md) to `docs/specs/<slug>.md`.
2. Fill every section. Every operational value becomes a config field (no magic numbers);
   every wire change states its `schema_version` posture; the CHARTER §4 invariant checklist
   must be answered, not skipped.
3. Register it in the table below with status `Definition`.
4. Implement behind the seams (registry / `Protocol` / config), citing `§` numbers in
   docstrings. Move status to `Implemented` when the gates are green and coverage meets the
   spec's floor; to `Validated` once the spec's hardware/bench exit criteria pass.

## Status legend

- **Definition** — spec written, not yet implemented.
- **Implemented** — code shipped and unit-tested (fakes-first), gates green.
- **Validated** — implementation confirmed against the spec's hardware/bench exit criteria.

## Specs

| Spec | Scope | Status |
| ---- | ----- | ------ |
| [PHASE0_ERRATA.md](PHASE0_ERRATA.md) | FPV ground-side: half-duplex wiring + echo suppression (E1) | Implemented |
| [PHASE1_SPEC_v1_1.md](PHASE1_SPEC_v1_1.md) | FPV telemetry ingest, link health, flight logger | Implemented (bench §8 pending → Validated) |
| [initiative-c-commanding-design.md](initiative-c-commanding-design.md) | Supervised two-way commanding (safety/auth/audit/health) | **Implemented** (code shipped; M2-gate clearance is a maintainer decision — see banner) |
| [initiative-e-inference.md](initiative-e-inference.md) | AI inference bridge (`meshsa.inference`) — Nemotron NIM + injectable HTTP-transport seam | **Implemented** (MVP + transport seam; Track-B hardening is Definition) |
| [initiative-scout.md](initiative-scout.md) | Vineyard structural-anomaly scouting: georef fusion + field map + offline survey export (`meshsa.scout`) | **Implemented** (fakes-first; §3 offline-export carve-out ratified 2026-07-05; hardware validation pending) |
| [initiative-d-perception.md](initiative-d-perception.md) | On-board multi-object tracker (`jetson_yolo_gcs`; read-only, advisory) | **Implemented** (fakes-first; §3 on-board-tracking carve-out ratified 2026-07-16; on-device validation pending) |

## Specs to author (tracked in the implementation plan)

These are queued by [../IMPLEMENTATION_PLAN.md](../IMPLEMENTATION_PLAN.md). Author each from
`TEMPLATE.md` before the corresponding track's code lands:

| Planned spec | Track | Purpose |
| ------------ | ----- | ------- |
| `initiative-d-perception.md` | C | `jetson_yolo_gcs` hardening — **precision-landing safety section is mandatory** (started: on-board tracker section landed 2026-07-16; C.1–C.6 hardening sections still to author) |
| `m3-richer-tracks.md` | D | SPI/FoV CoT + stable multi-UAS UIDs (M3.2; M3.1 already shipped additively) |
| `detection-cot-bridge.md` (retro) | 0.2 | Back-fill the shipped detection→CoT MARKER bridge |
| `observability-metrics.md` (retro) | 0.2 / A.1 | Back-fill metrics export + Grafana golden-signal dashboard |
| `m2-fts-e2e.md` | A.2 | Automated FreeTAKServer end-to-end CI job (non-coverage) |
| `m2-soak-fuzz.md` | A.3 | Soak/fuzz on real radios + MAVLink 2 signing research |
| `m4-store-and-forward.md` | F.1 | Meshtastic store-and-forward (research semantics first) |
| `m5-packaging.md` | F.2 | Reproducible multi-arch image + signed releases |
