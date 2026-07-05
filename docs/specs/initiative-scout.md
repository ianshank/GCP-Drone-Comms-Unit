# Initiative Scout — Vineyard structural-anomaly scouting + georeferenced field map

> **Status: Implemented.** (Definition → Implemented → Validated; see
> [README.md](README.md).) Software shipped fakes-first and gates green (871 tests, 98.7% cov);
> hardware/field validation (H1–H5) still moves it to `Validated`. Pairs with
> [../CHARTER.md](../CHARTER.md) (scope + invariants), [../ROADMAP.md](../ROADMAP.md) (milestone),
> and [../IMPLEMENTATION_PLAN.md](../IMPLEMENTATION_PLAN.md) (track). Code docstrings cite this
> spec's `§` numbers.

**Milestone / Initiative:** Initiative Scout  **Track:** Scout.0–Scout.5  **Author:** peer-review, 2026-07-05

> ## ✅ GATE — RESOLVED
>
> The mission-export deliverable (§1 Phase 3, `export_mission`) required a CHARTER §3 carve-out
> (mission/waypoint autonomy was out of scope). **The maintainer ratified a §3 carve-out on
> 2026-07-05 for offline survey generation + export for a human pilot to load** (no autonomy, no
> auto-upload, no in-flight action, no MAVLink writes) — recorded in [../CHARTER.md](../CHARTER.md)
> §3. `export_mission` ships wired into the `meshsa-scout gen-mission` CLI under that carve-out.

---

## 1. Scope

Turn a mapping-style survey flight (RGB camera + autopilot pose) into a **georeferenced,
deduplicated map of structural anomalies** in a vineyard block, rendered on the operator's
existing TAK map and an optional thin web view. Deliverables in priority order:

1. **Scout.0 — Contracts + replay harness** `[SW]`: `GeoDetection`/`Block` schemas and a
   synthetic boustrophedon replay that emits `Pose` + `Detection` at known ground-truth
   locations with configurable M8N-vs-RTK noise. Builds/tests green with no hardware.
2. **Scout.1 — Georeferencing core** `[SW]`: extend `meshsa.cv.geo` with a `Terrain` seam
   (flat + DEM), roll handling, a covariance-based ground-error estimate, and lens
   undistortion; plus the **Pose-fusion + true-AGL layer** the projection needs.
3. **Scout.2 — Fusion**: timestamp sync (max-skew guard), spatial dedup (cluster at
   `vine_spacing/2` for the RTK/A1 tier), and a per-block/session store.
4. **Scout.4 — Ground station**: emit each `GeoDetection` through the existing
   `detection_codec → MARKER → cot → TAK` path so anomalies render in ATAK/FreeTAKServer; add a
   thin `aiohttp` + MapLibre operator view for **tag/reject/inspect** and GeoJSON/CSV export.
5. **Scout.3 — Mission geometry**: row-aligned boustrophedon **coverage analysis** and
   `export_mission` to QGC `.plan` / ArduPilot `.waypoints` — **shipped** under the §3
   offline-survey carve-out ratified 2026-07-05 (wired into `meshsa-scout gen-mission`).
6. **Scout.5 — Companion glue** `[HW]`-gated: `PoseSource` (position + attitude + AGL) and a
   `DetectionSource` seam (replay feeder now; IMX500 backend later), verified against ArduPilot
   SITL + a fake detection feeder.

**Precision tier (confirmed):** A1 — vine-level, **requires RTK** (Track H2). Dedup clusters at
`vine_spacing/2`; the map shows per-vine pins. The A2 zone-level tier (stock M8N, zone polygons)
is a config change, not a rebuild, but is **not** the shipped default.

### Non-goals (explicitly deferred)

- **In-flight autonomy / auto-upload / BVLOS** — CHARTER §3. Mission output (if the carve-out
  ratifies) is an *offline file a human loads*, nothing more.
- **Real-time control loop / mid-flight reaction** (Fork B2) — the product is an accumulating
  map, not a control system.
- **Vine physiology** — vigor, water stress, early disease. RGB-from-altitude sees *structure*
  (missing/dead vines, canopy gaps, standing water, trellis damage, intrusion, debris), not
  physiology; those need multispectral/NIR + ground truth. Do not market as vine-health.
- **A meshsa dependency inside `jetson_yolo_gcs`** — the perception carve-out forbids it; the
  two `Detection` types are reconciled by the shared JSON frame contract, never a shared class.

---

## 2. Facts the implementation relies on

- **`meshsa.cv.geo` already implements the flat-ground ray-cast** (`project_to_ground`,
  `Camera`, `Pose`, `GroundFix`, `relative_bearing`, `destination`) and has **no production
  callers** (only `cv/__init__.py` re-export and `tests/test_cv_geo.py`, which asserts only
  `ce_m > 0`). It is therefore safe to extend in place, additively.
- **`geo.Pose` requires `alt_agl_m`, `heading_deg`, `pitch_deg`.** `transports/mavlink_source.py`
  reads **position only** from `GLOBAL_POSITION_INT` (no attitude), and its altitude is the
  autopilot's MSL/relative datum, **not AGL**. Producing a valid `Pose` requires fusing
  `ATTITUDE` and deriving true AGL (terrain-follow or DEM + datum reconciliation).
- **The MARKER wire path carries a positioned, labeled pin.** `detection_codec._REQUIRED =
  (src, msg_id, ts, lat, lon, label, confidence)`; lat/lon/ce ride a sibling `Position` block,
  `label` is the class. `cot.py` builds a per-track uid (`source:track_id`) so one anomaly is one
  updated ATAK marker. `CotCodec.stale_s` defaults to **120 s** — survey pins must set a long or
  disabled stale or they expire.
- **`cot.py:_encode_marker` serialises only `label/confidence/track_id/bearing_deg`.** Richer
  vineyard attributes (block/row/severity) are dropped on CoT round-trip unless the codec is
  extended — a core-codec change subject to the §6 additive-wire ritual.
- **Ground-error magnitude (why A1 needs RTK + DEM):** at 60 m AGL, ground error ≈ horizontal
  CEP (M8N ~2.5 m vs row spacing 1.5–2.4 m ⇒ a full row off); attitude error ≈ `alt·tan(σ)`
  (~1 m/deg). Flat-earth projection on a 10–15° slope injects ~3 m to multi-metre horizontal
  error at frame edge. RTK (cm-level) + AGL-correct DEM is the difference between "which vine"
  and "somewhere over there."

Each field-varying value above becomes a `ScoutConfig` field in §5, not a literal.

---

## 3. Architecture

```
Companion (thin)                          Ground station (meshsa.scout)
  PoseSource  ── pose (pos+att+AGL) ─┐
  DetectionSource ── pixel dets ─────┤─►  sync ─► georef (cv.geo+terrain) ─► dedup ─► store
  (replay | MAVLink+IMX500)          │                                              │
                                     │                    ┌──── detection_codec ─► MARKER ─► cot ─► TAK/ATAK
                                     └────────────────────┤
                                                          └──── aiohttp+MapLibre view (tag/reject/export)
```

**Seams (all injected `Protocol`s; tests reach every component with fakes — no hardware):**
- `PoseSource` — replay (synthetic) ↔ MAVLink (position + `ATTITUDE` + AGL).
- `DetectionSource` — replay feeder ↔ IMX500 backend (registered by extension, like
  `jetson_yolo_gcs` detectors).
- `Terrain` — flat plane (exists in `cv.geo`) ↔ DEM raster (`rasterio`, optional extra).
- `Store` — in-memory / SQLite / GeoJSON.

**Registry / config placement:** `meshsa.scout` is a new subpackage beside `cv/`, `command/`,
`fpv/`. It **may** import `meshsa.cv.geo`, `meshsa.models`, `meshsa.transports.mavlink_source`,
and the `detection`/`cot` codecs (unlike `jetson_yolo_gcs`, which stays meshsa-free). No new
transport/codec is required for the primary map path — the existing `detection` codec + a TAK leg
already carry a positioned MARKER; scout is a *producer* of detection frames, added without
editing the router, node, or models.

**Stateful I/O** lives in the sources/store, never in a codec; the georef and geometry modules
stay pure functions.

---

## 4. Behaviour / state model

- **Sync:** each `Detection` is matched to the nearest `Pose` by timestamp; if skew exceeds
  `sync_max_skew_s` the detection is **dropped and counted**, never projected against a stale
  pose (a stale pose silently mislocates the pin).
- **Georef degradation:** `project_to_ground` returns `None` at/above the horizon or with no
  usable AGL; the caller **must** degrade explicitly (drop + count, or emit a sensor-relative
  bearing via `relative_bearing`) — never fabricate a lat/lon.
- **Dedup:** project all, cluster in ground space at `dedup_radius_m` (≈ `vine_spacing/2` for
  A1); one ground-truth anomaly seen in K overlapping frames collapses to exactly one pin under
  RTK-level noise. Under M8N-level noise clusters *merge across vines* — retained as a regression
  test proving A1 needs RTK.
- **This is not a safety write path.** Scout issues **no** vehicle commands and no
  `LANDING_TARGET`; it only *reads* pose and *produces* map markers. The `export_mission` file
  (if ratified) is inert until a human loads it into their own GCS. There is therefore no
  fail-closed vehicle interlock here — the safety posture is "never emit a wrong pin silently"
  (drop-and-count on stale/failed projection), not "never move the aircraft."

---

## 5. Module specifications

`meshsa/scout/`: `schemas.py` (`GeoDetection`, `Block`), `sync.py`, `dedup.py`, `store.py`,
`survey.py` (coverage analysis + `export_mission.py`), `replay.py`, `protocols.py`
(`PoseSource`/`DetectionSource`/`Store` Protocols), and `pose.py` (attitude/AGL fusion).
Config→behaviour wiring helpers: `terrain.build_terrain`, `store.build_store`,
`pipeline.make_marker_codec`, and `cli.camera_from_config`. `meshsa/cv/geo.py` gains a `Terrain`
seam + roll + covariance error, all additive. Web view under `meshsa/scout/station/` (thin
`aiohttp` handlers + an embedded MapLibre page built with DOM-safe `textContent`, no `innerHTML`).

> **No magic numbers (CHARTER §4.5).** New `ScoutConfig` Pydantic sub-model composed into
> `NodeConfig` (mirroring `HealthConfig`/`NemotronConfig`), wired through `NodeConfig.from_env`.

| Field | Type | Default | Env binding | Meaning |
| ----- | ---- | ------- | ----------- | ------- |
| `rtk_enabled` | bool | `true` | `MESHSA_SCOUT_RTK_ENABLED` | A1 vine-level (true) vs A2 zone (false) |
| `vine_spacing_m` | float | `2.0` | `MESHSA_SCOUT_VINE_SPACING_M` | as-planted vine spacing |
| `row_spacing_m` | float | `2.4` | `MESHSA_SCOUT_ROW_SPACING_M` | row spacing |
| `dedup_radius_m` | float | `1.0` | `MESHSA_SCOUT_DEDUP_RADIUS_M` | cluster radius (≈ vine_spacing/2) |
| `sync_max_skew_s` | float | `0.05` | `MESHSA_SCOUT_SYNC_MAX_SKEW_S` | drop detections past this pose skew |
| `attitude_sigma_deg` | float | `1.0` | `MESHSA_SCOUT_ATTITUDE_SIGMA_DEG` | attitude 1σ for the error model |
| `pos_cep_m` | float | `0.05` | `MESHSA_SCOUT_POS_CEP_M` | position CEP for the error model (RTK ≈ 5 cm) |
| `marker_stale_s` | float | `86400.0` | `MESHSA_SCOUT_MARKER_STALE_S` | CoT stale for survey pins (override the 120 s default) |
| `forward_overlap` | float | `0.75` | `MESHSA_SCOUT_FORWARD_OVERLAP` | survey forward overlap |
| `side_overlap` | float | `0.65` | `MESHSA_SCOUT_SIDE_OVERLAP` | survey side overlap |
| `survey_alt_agl_m` | float | `60.0` | `MESHSA_SCOUT_SURVEY_ALT_AGL_M` | planned survey altitude |
| `survey_cruise_speed_ms` | float | `10.0` | `MESHSA_SCOUT_SURVEY_CRUISE_SPEED_MS` | QGC `.plan` cruise speed |
| `survey_hover_speed_ms` | float | `5.0` | `MESHSA_SCOUT_SURVEY_HOVER_SPEED_MS` | QGC `.plan` hover speed |
| `camera_img_w` / `camera_img_h` | int | `1920` / `1080` | `MESHSA_SCOUT_CAMERA_IMG_W` / `_H` | image size (calibration H1) |
| `camera_h_fov_deg` / `camera_v_fov_deg` | float | `70.0` / `42.0` | `MESHSA_SCOUT_CAMERA_H_FOV_DEG` / `_V_FOV_DEG` | camera FOV (calibration H1) |
| `dem_path` | str \| None | `None` | `MESHSA_SCOUT_DEM_PATH` | DEM GeoTIFF (via `build_terrain`); `None` ⇒ flat plane |
| `store_path` | str | `":memory:"` | `MESHSA_SCOUT_STORE_PATH` | SQLite store path (via `build_store`); `":memory:"` ⇒ in-memory |
| `station_host` / `station_port` / `station_token` | str/int/str | `127.0.0.1` / `8099` / `""` | `MESHSA_SCOUT_STATION_*` | operator-station bind + bearer token |
| `enabled` | bool | `false` | `MESHSA_SCOUT_ENABLED` | opt-in flag for a node-hosted scout |

`cv/geo.py`'s `_POINTING_UNCERTAINTY_DEG = 1.0` and the named `_LEGACY_ERROR_FLOOR_M = 5.0` are
**retained as a legacy fallback**: `project_to_ground` uses the covariance model
(`ground_error(range, pos_cep_m, att_sigma_deg)`) when scout supplies `pos_cep_m`/`attitude_sigma_deg`,
and falls back to the legacy estimate only when neither is given (preserving existing callers).

---

## 6. Wire / schema posture (backward compatibility)

- **Additive, no bump — for the minimal marker.** A `GeoDetection(lat, lon, class, confidence,
  error)` rides the existing `MARKER` `Envelope` unchanged: class → `Detection.label`, error →
  `Position.ce`, position → `Position`. Old readers see byte-identical output.
- **Richer vineyard attributes (block_id, row_id, severity) → additive-optional + a core-codec
  touch.** They are new optional keys emitted via `exclude_none` (M3.1 additive pattern, no
  `SCHEMA_VERSION` bump) **but** reaching ATAK requires extending `cot.py:_encode_marker`; they
  are dropped on CoT round-trip until then. Treat as a follow-on, not Scout.0.
- **If any change becomes envelope-shape-altering**, follow the full bump ritual
  (`meshsa.version` + tests + docs + `CHANGELOG.md`) via the `meshsa-schema-version-bump` skill.

---

## 7. Test plan (by category)

Fakes-first, no hardware in unit tests. **Coverage floor: meshsa ≥90% total** (this repo enforces
`--cov-fail-under=90` repo-wide; scout ships at ~100%). Pre-declared exempt surface: only the
`rasterio.open(...)` **file read** in `load_dem` is `# pragma: no cover` (I/O glue, Invariant 6) —
the CI `test` job installs `[dev,inference]`, not the `geo` extra, so rasterio is absent. The
DEM's *data-shaping* logic is a pure `grid_from_band` function tested with an in-memory band, the
bilinear math is `GriddedTerrain` (fully tested), the `build_terrain` selection + no-rasterio
fallback are tested, and `load_dem`'s "geo extra missing" `ImportError` is asserted. The MapLibre
**JS frontend** is an embedded page (no `.py` logic to cover); all station behaviour lives in
testable `aiohttp` handlers (precedent: `meshsa.llm.server`). The `run-station` serve loop and the
process/module entry points are the only other pragmas — legitimate socket/entry glue.

- **Unit** — georef (extended `cv.geo`), pose/AGL fusion, sync, dedup, survey geometry, store,
  `.plan`/`.waypoints` emit — each with fakes / `FakeClock`.
- **Integration** — replay flight → georef → dedup → store → MARKER frames at expected coords;
  end-to-end pin count and locations asserted.
- **Functional / edge** — sync skew boundary (drop past `sync_max_skew_s`), horizon/no-AGL →
  `None` degrade, DEM-missing → flat-plane fallback, empty block, stale override applied.
- **Property-based (Hypothesis, mirror `test_cv_geo.py`)** — nadir→known point within ε; injected
  1° pitch → predicted lateral offset; pixel→ground→pixel < 1 px; error grows with alt & σ; DEM
  corrects a flat-earth slope miss.
- **Regression** — the **M8N-noise cross-vine merge** test (empirical proof A1 needs RTK).
- **Golden vectors** — `.plan` validates against the QGC schema; a wrong-decode negative
  assertion on the survey/waypoint emitters.

---

## 8. Exit criteria

- **Mechanism (binary):** §7 green; gates (`ruff`/`ruff format`/`mypy --strict`/`pytest`) green
  from `packages/meshsa`; coverage floor met; `CHANGELOG` + `NEXTSTEPS` updated; spec status →
  `Implemented`. `export_mission` ships under the ratified §3 offline-survey carve-out.
- **Validation (separate → `Validated`):** RTK integration (H2), camera calibration (H1), a DEM
  tile (H3), and a field pass (H5) that measures pin accuracy vs ground truth within the A1 error
  budget on one block. Thresholds stay provisional until measured (mirror the FPV §8 split).

---

## 9. CHARTER §4 invariant checklist

| # | Invariant | How this design preserves it |
|---|-----------|------------------------------|
| 1 | Open/closed registry extensibility | Primary map path reuses the existing `detection` codec + a TAK leg; scout is a producer, not a router/node/models edit. IMX500 detection backend registers by extension like `jetson_yolo_gcs`. |
| 2 | Versioned, backward-compatible wire | §6: minimal marker additive/no-bump; richer attrs additive-optional + a scoped `cot.py` extension; envelope-shape changes take the full bump ritual. |
| 3 | DI via `Protocol`, tests need no hardware | `PoseSource`/`DetectionSource`/`Terrain`/`Store` injected; replay + fakes reach every module; no radios/GPU/autopilot in unit tests. |
| 4 | Stateful I/O in transports/services, not codecs | I/O in sources + store; georef and geometry are pure functions; codecs stay per-frame maps. |
| 5 | Config-driven, no magic numbers | §5 `ScoutConfig` table; camera intrinsics + survey speeds are config (not module constants); `cv.geo`'s residual literals are an explicit named legacy fallback. |
| 6 | Gates green; hardware glue is the only `# pragma: no cover` | ~100% on scout; only the `rasterio.open` file read, the `run-station` serve loop, and process/module entry points are pragma'd (§7); `grid_from_band` + `build_terrain` fallback + the "geo extra missing" error are tested. |
| 7 | No secrets / machine fingerprints in repo | No credentials; DEM path / store path / block geometry are runtime config; the built-in `sample_block()` and any operator DEM tile carry no secrets. |
