# Gap Analysis — `meshsa.scout` (vineyard scouting)

Date: 2026-07-05
Scope: the `meshsa.scout` subsystem + additive `cv/geo.py`/`config.py`/`netauth.py` changes on
branch `claude/peer-review-revised-plan-ks9dgl` (PR #25). Pairs with
[specs/initiative-scout.md](specs/initiative-scout.md) and [CHANGELOG.md](../CHANGELOG.md).

## Summary

| Dimension | Result |
| --------- | ------ |
| Tests | **892 passed, 5 skipped** |
| Coverage (meshsa) | **99.14% line/branch** (gate 90); scout modules ~100% |
| Lint / format | `ruff check` + `ruff format --check` **clean** (packages/meshsa + flightctl) |
| Type-check | `mypy --strict src` **clean**; root `mypy.ini` flightctl step **clean** |
| Packaging | `python -m build` **clean** |
| Health-check | `meshsa-scout --health-check` **exit 0** (3 pins, worst error 0.24 m) |

Inputs: my scan, the adversarial correctness review, the Copilot PR review (4 comments), and a
per-file coverage audit. The subsystem was already green; the findings below were latent defects
and drift, now remediated.

## 1. Dead config (fields defined + tested but never wired) — **fixed**

| Finding | Impact | Action |
| ------- | ------ | ------ |
| `marker_stale_s` never reached `CotCodec.stale_s` | Scout MARKERs expire at the 120 s CoT default; survey pins vanish in 2 min | `pipeline.make_marker_codec(config)` builds the MARKER CoT codec with the configured stale; tested |
| `dem_path` never consumed — CLI hardcoded `FlatTerrain` | DEM slope-correction seam dead at runtime | `terrain.build_terrain(dem_path, mean_elev)` → `load_dem` or flat; wired in `cli`; rasterio-absent → warn + flat fallback |
| `store_path` never consumed — always `InMemoryStore` | SQLite persistence seam unconnected | `store.build_store(store_path)` → `SqliteStore` vs `InMemoryStore`; wired in `cli` |
| `DEFAULT_CAMERA` intrinsics hardcoded on `replay`/`gen-mission` | Camera FOV/size (calibration-varying) not config-driven (Invariant 5) | New `camera_*` `ScoutConfig` fields + `cli.camera_from_config`; retires the constant on production paths |

## 2. Security — **fixed**

| Finding | Impact | Action |
| ------- | ------ | ------ |
| Station map click handler used `innerHTML` with feature `cls`/`id` | XSS sink if a detection class/id carries markup | Rebuilt the panel with `createElement`/`textContent`/`addEventListener`; no `innerHTML` |

## 3. Efficiency — **fixed**

| Finding | Impact | Action |
| ------- | ------ | ------ |
| `TimeSync.align` linear scan × batch-sized buffer | O(detections × poses) for a full survey | Lazily-sorted index + `bisect`; O(log n) per align, correct under out-of-order inserts |
| `coverage_fraction` scans every transect per sample | O(samples × transects) | Band transects by `v`, binary-search the reachable band per sample |

## 4. Doc drift — **fixed**

| Finding | Action |
| ------- | ------ |
| CHANGELOG said the past-nadir change "rejects `depression > 90°`" | Corrected to "reflects" (complementary depression, azimuth+180) |
| Spec §7 claimed a committed GeoTIFF fixture tested `load_dem` (none existed) | §7 rewritten: only the `rasterio.open` read is pragma'd; `grid_from_band`/`build_terrain`/ImportError are tested |
| Spec §5 module list named `sources.py`; config table omitted camera/speeds/station fields | Reconciled to `protocols.py`+`replay.py`; table completed; "folded literals" corrected to "legacy fallback" |

## 5. Test coverage — **closed**

Added error/branch tests: health-check pin-count-mismatch + error-budget-exceeded exits; station
auth-denial on `/export.*`+`/block` and malformed-body → 400; `gen-mission` single-output; `TimeSync`
out-of-order + index invalidation; sparse `coverage_fraction`; `build_terrain`/`build_store`/
`grid_from_band`/`load_dem`/`make_marker_codec`/`camera_from_config`; polygon/waypoint lon-range;
replay no-noise branch. Scout modules moved from 91–99% to ~100% (global 98.71% → 99.14%).

## 6. Out of scope (documented, not defects)

- **Scout.5 `[HW]` seams** — a real MAVLink `PoseSource` (fuses `mavlink_source` + `ATTITUDE` via
  `PoseFuser`) and an IMX500 `DetectionSource` backend are hardware-gated; only replay impls exist.
- **Offline map tiles** — the station embeds MapLibre/OSM from a CDN; a fully-offline field unit
  should vendor the asset (noted in `station/_html.py`).
- **`numpy`** — deliberately not added; terrain interpolation stays pure-Python to keep `meshsa`'s
  minimal core deps (pydantic + structlog) and a green CI `test` job without the `geo` extra.

## 7. Verification record

```text
$ cd packages/meshsa
$ ruff check .                         → All checks passed!
$ ruff format --check .                → 178 files already formatted
$ python -m mypy src                   → Success: no issues found in 91 source files
$ python -m mypy --config-file ../../mypy.ini ../../flightctl/run_commander.py ../../flightctl/run_gateway.py
                                       → Success: no issues found in 2 source files
$ python -m pytest                     → 892 passed, 5 skipped; coverage 99.14% (gate 90)
$ python -m build                      → Successfully built meshsa-0.3.0
$ python -m meshsa.scout --health-check → scout health-check OK: 3 pins, worst error 0.24 m
```
