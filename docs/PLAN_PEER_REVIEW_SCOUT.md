# Peer Review — "Vineyard SCOUT + Ground Station" plan + Revised plan

> Reviewed 2026-07-05 against the working tree at the head of
> `claude/peer-review-revised-plan-ks9dgl`. Every verdict was checked against actual files, not
> the plan's prose, and then **adversarially re-reviewed against the source**. Part 1 is the
> claim-by-claim review; Part 2 is the regenerated plan with the corrections folded in; Part 3 is
> the CHARTER carve-out proposal the mission-export deliverable requires. The executable spec is
> [specs/initiative-scout.md](specs/initiative-scout.md) (status **Definition**).

## Context

The reviewed plan ("Vineyard SCOUT + Ground Station") is a build spec for a **structural-anomaly
scouting drone + map-first ground station** for a Napa vineyard. It is well-structured on its own
terms, but it was written as a **greenfield `vinescout/` package** with **no reference to this
repository** — which is a MAVLink+mesh → TAK/CoT situational-awareness bridge governed by a stable
`docs/CHARTER.md` and a spec-driven merge rule. Reviewed in place, the plan reinvents primitives
the repo already ships and collides with one CHARTER non-goal. The maintainer confirmed five forks
that shape the revision: **integrate into this repo; A1 vine-level + RTK; DetectionSource seam +
synthetic replay; TAK-first ground station; home = a `meshsa.scout` subpackage.**

---

## Part 1 — Peer review

### Overall assessment

The plan's engineering instincts match this repo's culture closely — hardware-gating, replay-first
offline builds, `Protocol` seams, config-only tunables. Its **one structural flaw is that it is
blind to the host repo**: ~40–60% of it already exists as tested, hardware-free code, and its
headline mission-planning module is an explicit CHARTER non-goal. Its physics (why RTK is
non-negotiable for vine-level pins) is sound and survives review intact. Re-cast as a reuse-first,
spec-driven, charter-amended `meshsa` initiative, it is a strong plan.

### What the plan got right (verified in code)

- **Hardware-gating spine** — `[SW]/[HW]` seams, "builds green with no hardware against a synthetic
  replay harness," swap-points for pose/detection/terrain/store. This is exactly how
  `jetson_yolo_gcs` and `meshsa.fpv` are built. Keep.
- **RTK-necessity physics — and it is not overstated.** `cv/geo.py` projects with
  `range = alt/tan(depression)` under a flat-ground assumption; on a 10–15° Napa slope that injects
  ~3 m (moderate off-nadir) to multi-metre (frame-edge, 90° HFOV) horizontal error vs ~1.5–2.4 m
  row spacing. The "M8N clusters merge across vines" idea is a genuine empirical proof and is kept
  as a regression test.
- **Detection-class honesty** (structure from RGB, not vigor/physiology) and the
  Part-107/BVLOS/Part-137 notes — accurate, kept verbatim as spec non-goals.
- **Georef-on-ground-station, thin-companion split** — the right division; matches the repo (heavy
  detector process is `jetson_yolo_gcs`; projection is a pure importable module).

### Claim-by-claim verdicts

| # | Plan claim / assumption | Verdict | Evidence |
| - | ----------------------- | ------- | -------- |
| 1 | Build georef (`camera`/`transforms`/`terrain`/`project`) from scratch in `vinescout/` | **REINVENTS** | `packages/meshsa/src/meshsa/cv/geo.py` already provides `project_to_ground`, `Camera`, `Pose`, `GroundFix`, `relative_bearing`, `destination` (tested in `tests/test_cv_geo.py`). The plan's `project()` + `pos_cep + alt·tan(att_σ)` error is ~90% this module. |
| 2 | (implicit) extending georef is risky | **REFUTED** | `project_to_ground`/`GroundFix`/`Pose` have **no production callers** — only `cv/__init__.py` re-export and the test. `detection_codec.py`/`models.py` name `meshsa.cv.geo` in **docstrings only**. Extend freely; `test_cv_geo.py` asserts only `ce_m > 0`, so the error-model rewrite is low-risk. |
| 3 | `PoseSource` = reuse `mavlink_source` | **PARTIALLY TRUE (biggest hole)** | `transports/mavlink_source.py` reads **position only** from `GLOBAL_POSITION_INT` — no roll/pitch/yaw — and its `alt` is MSL/relative, **not the `alt_agl_m` `project_to_ground` requires**. A valid `geo.Pose` needs `ATTITUDE` fusion + a true-AGL story (terrain-follow or DEM + datum reconciliation). Real new code, not a drop-in. |
| 4 | `mission/survey.py` + `.plan`/`.waypoints` export | **CHARTER COLLISION** | Mission/waypoint generation is an explicit §3 non-goal, reaffirmed in all three carve-outs. "Offline generation+export for a human to load" is distinguishable from autonomy/auto-upload, so a carve-out is defensible — but it **is** a scope expansion into mission planning and must be ratified before code (see Part 3). |
| 5 | Build a FastAPI+MapLibre map to show accumulating geolocated pins | **PARTIALLY REINVENTS** | `detection_codec._REQUIRED = (src,msg_id,ts,lat,lon,label,confidence)` → MARKER `Envelope` (lat/lon/ce in a `Position` block, `label`=class) → `cot.py` per-track uid → ATAK/FTS already renders one persistent, positioned pin per anomaly. Minimal `GeoDetection` rides MARKER additively, **no schema bump**. |
| 6 | Richer per-pin attributes ride the map "for free" | **OVERSTATED** | `cot.py:_encode_marker` serialises only `label/confidence/track_id/bearing_deg`; block/row/severity are dropped on CoT round-trip until the core codec is extended (additive-optional ritual). And `CotCodec.stale_s` defaults to **120 s** → survey pins expire in 2 min unless scout sets a long/disabled stale. |
| 7 | Tag/reject/inspect via ATAK reuse | **REFUTED (must build)** | The MARKER path has no triage state and ATAK edits don't flow back. Tag/reject/inspect is genuinely the thin web view's job — the plan's internal split is correct, but the value is not free. |
| 8 | Stack: FastAPI, rasterio, picamera2 | **DRIFTS FROM REPO** | None are in-tree. HTTP here is `aiohttp` (`llm/server.py`, `health.py`). Align: web = `aiohttp`; DEM = `rasterio` as an optional extra + mypy `ignore_missing_imports`; IMX500 = lazy import behind the detection registry. |
| 9 | `schemas.py` reconciles the two `Detection` types | **ARCHITECTURE VIOLATION if type-merged** | `jetson_yolo_gcs.detection.base.Detection` (pixel) cannot share a Python type with `meshsa.models.Detection` (wire) — the perception carve-out mandates jetson carries **no meshsa dependency**. Reconcile via the shared **JSON frame contract** `detection_codec` already speaks, never a shared class. |
| 10 | Terrain v2 (DEM) sequenced "later" | **MIS-SEQUENCED for A1** | For vine-level precision on Napa's hills, the DEM is on the critical path — and its dominant value is **AGL correctness first**, ray-slope second. Elevate into the georef phase's error budget. |
| 11 | No spec / process gate | **MISSING** | `docs/specs/README.md`: "a feature without a spec does not merge." A `docs/specs/` spec (from `TEMPLATE.md`, §9 invariant checklist answered, cited by `§` from code) must land first. Authored here as `specs/initiative-scout.md` (Definition). |
| 12 | Config = a bespoke `config.py` + grep meta-test | **PARTIALLY OVERTAKEN** | The repo already enforces no-magic-numbers via Pydantic config models (Invariant 5). Add a `ScoutConfig` composed into `NodeConfig` with `MESHSA_SCOUT_*` bindings; fold `cv/geo.py`'s hardcoded `_POINTING_UNCERTAINTY_DEG = 1.0` and `+5.0` floor into it. |

### Material findings the plan missed

1. **Pose is the real Phase-1 work, not georef math.** The projection exists; feeding it a correct
   `Pose` (attitude fusion + true AGL) does not. This is the single largest under-specified chunk.
2. **Coverage/Invariant-6 friction.** The repo enforces `--cov-fail-under=90` repo-wide and permits
   `# pragma: no cover` only for hardware/socket glue. `rasterio` DEM sampling needs a committed
   fixture GeoTIFF; a MapLibre JS frontend is invisible to pytest — keep JS thin, `omit` it, and
   put logic in testable `aiohttp` handlers. Pre-declare this surface or it drags the floor red.
3. **Phase-3 governance risk.** The mission export is the plan's headline value *and* the most
   likely to be denied. Phases 0–2 + 4 must deliver standalone value (coverage *analysis* + georef
   + dedup + TAK/web triage) that survives a rejection; only `export_mission` is gated.
4. **`CotCodec.stale_s = 120 s`** silently expires survey pins — a config fix, but unmentioned.
5. **`Detection.confidence` is required** (no default) — the replay generator must always populate
   it.

---

## Part 2 — Regenerated plan (corrections folded in)

Home: `meshsa.scout` subpackage (may import `cv.geo`, `models`, `mavlink_source`, `cot`). Precision
**A1 + RTK**. **B1** (no control loop). `DetectionSource` `Protocol` seam + **synthetic replay
now**, IMX500 later. **TAK-first** map + thin `aiohttp`+MapLibre triage view.

### Phase G — Governance + spec (docs-only; blocks all code)
- Raise the §3 carve-out in Part 3 for maintainer ratification (do **not** edit CHARTER in
  passing). Author `specs/initiative-scout.md` (Definition; registered in `specs/README.md`). Add a
  NEXTSTEPS entry. **DoD:** spec merged as Definition; carve-out recorded for decision.

### Phase 0 — Contracts + replay `[SW]`
- `GeoDetection`/`Block` schemas; reuse `models.Detection` on the wire; replay **always populates
  `confidence`**. `scout/replay.py`: boustrophedon flight over `tests/data/block.geojson` emitting
  `Pose`+`Detection` at known truth with M8N-vs-RTK noise. **DoD:** stream + injected-truth test.

### Phase 1 — Georef + Pose/AGL (crown jewel) `[SW]`
- **Extend `cv.geo` additively**: `Terrain` seam (flat + DEM via `rasterio` extra), roll,
  covariance error `pos_cep + alt·tan(att_σ)` (constants → `ScoutConfig`), lens undistort.
- **New Pose-fusion + AGL layer**: fuse `ATTITUDE` + position → `Pose`; derive AGL from
  DEM/terrain-follow. **DoD (mirror `test_cv_geo.py`):** nadir→point within ε; 1° pitch → predicted
  offset; pixel→ground→pixel < 1 px; error grows with alt & σ; DEM corrects a flat-earth slope miss.

### Phase 2 — Fusion `[SW]`
- `sync.py` (nearest-ts, `sync_max_skew_s` drop-and-count), `dedup.py` (cluster `vine_spacing/2`),
  `store.py` (SQLite/GeoJSON). **DoD:** 1 truth in K frames → 1 pin under RTK noise; keep the
  **M8N cross-vine-merge regression test**.

### Phase 3 — Mission geometry `[SW]`, GATED on Phase G
- `survey.py` **coverage analysis** ships regardless; `export_mission.py` (QGC `.plan` + ArduPilot
  `.waypoints`) **merges only if the carve-out ratifies**. **DoD:** 100% coverage at side-overlap;
  waypoint count/spacing asserted; `.plan` validates against the QGC schema.

### Phase 4 — Ground station `[SW]`
- Primary: emit each `GeoDetection` via `detection_codec`→MARKER→`cot.py`→TAK so pins render in
  **ATAK** (set non-default `marker_stale_s`). Secondary: thin `aiohttp`+MapLibre view (boundary +
  live pins + tag/reject/inspect + GeoJSON/CSV export). **DoD:** pins in ATAK/FTS at expected
  coords; web view round-trips valid GeoJSON/CSV. **Deliverable is the field map, not video.**

### Phase 5 — Companion glue `[HW]`-gated (stubs+contracts now)
- `PoseSource` = augmented mavlink (position + attitude + AGL); `DetectionSource` = replay feeder
  now, IMX500 backend later. **DoD (simulated):** ArduPilot **SITL** + fake feeder → correct fused
  stream; real IMX500 documented + on-device, not in CI.

### Dependencies, config & coverage (repo rules)
- New heavy deps → **optional extras** + matching mypy `ignore_missing_imports` in
  `packages/meshsa/pyproject.toml` and root `mypy.ini`: `rasterio`, `aiohttp` (existing). **Never
  FastAPI; never core `dependencies`.**
- `ScoutConfig` Pydantic sub-model into `NodeConfig` (mirror `HealthConfig`/`NemotronConfig`), env
  prefix `MESHSA_SCOUT_`, wired through `from_env`. Every tunable a field with a default.
- Coverage ≥90% repo-wide; DEM tested via a committed fixture GeoTIFF; MapLibre JS `omit`-ed with
  logic in testable `aiohttp` handlers; any socket-glue pragma flagged as an Invariant-6 stretch
  for maintainer sign-off. Gates from `packages/meshsa`.

### Parallel HARDWARE / DATA track (gates usefulness, not a coding task)
| ID | Task | Blocks |
|----|------|--------|
| H1 | Camera calibration → real intrinsics/distortion into `ScoutConfig` | Georef accuracy |
| H2 | **RTK integration** (rover + NTRIP/base) → corrected pose to Pixhawk | Fork A1 entirely |
| H3 | DEM tile (USGS 3DEP / Napa LiDAR) → `terrain` DEM loader | AGL + slope accuracy |
| H4 | **Dataset + IMX500 model** (fly, label, train, Sony toolchain convert) | Any real detection |
| H5 | Field validation: ground-truth one block; measure pin accuracy; tune | Trust |

---

## Part 3 — Proposed CHARTER §3 carve-out (for maintainer decision — NOT applied)

> This text is **a proposal only**. Per CHARTER §6, a scope change is surfaced for a human
> decision and, if ratified, recorded as a dated §3 carve-out by the maintainer. It is reproduced
> here so the decision can be made against concrete wording; the CHARTER itself is unchanged.

**Carve-out (proposed — offline survey generation & export only).** A new self-contained
subsystem (`meshsa.scout`) MAY **generate and export** a coverage/lawnmower survey plan
(QGC `.plan`, ArduPilot `.waypoints`) as an **offline file for a human pilot to review and load**
into their own GCS. Constraints (all required):
- **No autonomy, no auto-upload, no in-flight action.** Scout never uploads a mission, never
  commands the vehicle, and issues no MAVLink writes (no `LANDING_TARGET`, no arm/mode/RC). The
  file is inert until a human loads it. BVLOS/swarm autonomy stay out of scope.
- **Human-in-the-loop by construction.** The output is a file on disk; a Part-107 pilot reviews
  and flies it. This is *planning aid*, not a mission-execution path.
- **Same invariants as the rest of the repo.** Added behind `Protocol`/registry seams; every
  operational value is a `ScoutConfig` field with a default; unit tests use fakes and need no
  hardware; gates stay green at the ≥90% floor.
- **Read-only on the vehicle otherwise.** Scout consumes pose (read) and produces map markers;
  it does not lift the repo's read-by-default stance for any command.

This remains a bounded offline planning aid, not a general GCS or an autonomy platform; every
other §3 non-goal stands. Until ratified, `export_mission.py` does not merge; all other scout
work (georef, fusion, coverage *analysis*, field map, triage) proceeds independently.
