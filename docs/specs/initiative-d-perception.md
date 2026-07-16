# Initiative D — Perception: on-board multi-object tracker (read-only)

> **Status: Implemented.** (Definition → Implemented → Validated; see [README.md](README.md).)
> Pairs with [../CHARTER.md](../CHARTER.md) (§3 perception carve-out 2026-06-20 + on-board
> tracking carve-out 2026-07-16; §4 invariants), [../ROADMAP.md](../ROADMAP.md) (M3 richer
> tracks), and [../IMPLEMENTATION_PLAN.md](../IMPLEMENTATION_PLAN.md) (Track C). Code docstrings
> cite this spec's `§` numbers.

**Milestone / Initiative:** Initiative D (perception)  **Track:** C  **Author:** ianshank / 2026-07-16

> **Note on scope.** This spec covers the **on-board multi-object tracker** only. The broader Track C
> precision-landing hardening items (C.1 heartbeat-gate / cadence-floor, C.2 `LOCAL_NED`, C.3
> TIMESYNC, C.4 Hailo `.hef`, C.5 `/healthz`, C.6 runbook — see
> [../IMPLEMENTATION_PLAN.md](../IMPLEMENTATION_PLAN.md)) are authored separately as they land.
> §4 below is the precision-landing safety section **as it pertains to the tracker**: the tracker
> is strictly read-only and must never touch the `LANDING_TARGET` write path.

---

## 1. Scope

Add an on-board multi-object tracker to `jetson_yolo_gcs` that assigns a **stable id** to detected
objects across frames, so one physical object is one id rather than per-frame churn.

Deliverables (priority order):

1. A tracker seam — `TrackerBase` ABC + `tracker_registry` + `build_tracker` — mirroring the
   detector seam; adding a backend never edits the pipeline.
2. A Norfair backend (`norfair`, BSD-3-Clause; Kalman-SORT), behind an optional `[tracker]` extra
   with lazy import (package import stays light).
3. Pipeline integration: the tracker runs after detection, independent of the stream/bridge, and
   surfaces `tracks_active` / `tracks_total` / `dropped_tracks` in `Pipeline.snapshot()`.
4. Config group `TrackerSettings` (`TRACKER_*`), disabled by default.

### Non-goals (explicitly deferred)

- **No CoT emission and no geodetic projection.** The tracker does not feed the `meshsa`
  detection→CoT path; the jetson→`meshsa` detection emitter is a separate future spec (it, not this
  spec, decides the per-detection id wire contract). Respects CHARTER §3 (self-contained; no meshsa
  dependency).
- **No `LANDING_TARGET` behaviour change.** The tracker never influences which target is selected or
  published (§4). No target-lock, no hysteresis.
- **No autonomy / target-following / terminal guidance** (CHARTER §3 non-goals stand).

---

## 2. Facts the implementation relies on

Verified against tryolabs/norfair **2.3.0** (PyPI + master source):

- `Tracker.__init__(distance_function, distance_threshold, hit_counter_max=15,
  initialization_delay=None, ...)` — `distance_threshold` is **required, no default**.
- The built-in `"euclidean"` distance is SciPy `cdist` over the raw point coordinates: **pixel
  units, no normalisation**. The README quick-start uses `distance_threshold=20`. (A normalized
  `create_normalized_mean_euclidean_distance(h, w)` factory exists for a future config swap.)
- `Tracker.update(detections) -> List[TrackedObject]`. Objects still inside `initialization_delay`
  are **withheld** from that list and, if seen, carry `id is None` — hence the defensive skip.
- Hard runtime deps: `numpy<2.0.0`, `scipy>=1.5.4`, `filterpy` (unmaintained), `rich`. The
  `numpy<2` ceiling must be checked against the `[ultralytics]` extra before co-installing (§8).
- Norfair ships `py.typed`; `norfair.*`/`numpy.*` are added to the mypy `ignore_missing_imports`
  override so `mypy --strict` passes whether or not the extra is installed in the lint env.

---

## 3. Architecture

```
camera → detector.detect() → result ─┬───────────────► _select_target → LANDING_TARGET  (UNCHANGED)
                                      └─ tracker.update(result) → track counters → snapshot()  (NEW, read-only)
```

- **Seam:** `tracking/base.py::TrackerBase(ABC)` — `update(DetectionResult) -> tuple[TrackedDetection,
  ...]`; `TrackedDetection = (detection: Detection, track_id: int)` carries the id **without**
  mutating the frozen `Detection`.
- **Registry:** `tracking/factory.py::tracker_registry` (reuses `core.registry.Registry`);
  `build_tracker(settings, *, backend=None)` lazily imports the backend module to register it.
- **Backend:** `tracking/norfair_backend.py::NorfairTracker`. Two `# pragma: no cover` seams isolate
  the heavy-dep glue — `_build_tracker` (real `norfair.Tracker`) and `_to_norfair_detections`
  (numpy + `norfair.Detection`) — and both are injectable, so the id map-back logic is fake-tested
  with no `norfair`/`numpy` import. The map-back (skip `id is None`; `int(id)`; recover source via
  `last_detection.data`) stays in the covered path.
- **Pipeline:** an injected `tracker: TrackerBase | None` collaborator (built by `build_pipeline`
  only when `TRACKER_ENABLED`). `step()` calls `_update_tracks(result)` after the detection guard,
  independent of the bridge. Stateful track set lives in the tracker; the pipeline holds only int
  counters. Added to the `close()` tuple.

Tests reach every component with fakes — no `norfair`, GPU, camera, or autopilot.

---

## 4. Behaviour / safety model (precision-landing write-path protection)

The `LANDING_TARGET` publisher is the highest-risk path in this package. The tracker is walled off
from it:

- **Read-only.** The tracker output feeds only `tracks_active`/`tracks_total`/`dropped_tracks` in
  the health snapshot. It is **never** passed to `_select_target` or `_publish_target`; target
  selection remains "highest-confidence detection (optionally class-filtered)", byte-for-byte
  identical with the tracker enabled or disabled. This is pinned by a regression test (§7).
- **Fail-safe, never fail-loud.** Unlike the publish path, a tracker `update()` fault is
  **dropped-and-counted** (`dropped_tracks`, throttled log) and the loop continues — the tracker is
  advisory, so a fault must not stop the camera/stream/publish loop. `tracks_active` retains its last
  good value on a fault.
- **Off by default.** `TRACKER_ENABLED=false` ⇒ the tracker is never built; counters stay 0 and
  behaviour is identical to a build without tracking.
- **No write authority.** The tracker issues no MAVLink/RC/command output of any kind.

---

## 5. Module specifications

| Module | Public surface | Satisfies |
| ------ | -------------- | --------- |
| `tracking/base.py` | `TrackedDetection`, `TrackerBase.update/close` | new ABC seam |
| `tracking/factory.py` | `tracker_registry`, `build_tracker` | registry (Invariant 1) |
| `tracking/norfair_backend.py` | `NorfairTracker`, `@tracker_registry.register("norfair")` | backend |
| `core/config.py` | `TrackerSettings` | config (Invariant 5) |
| `pipeline.py` | `tracker` DI param; `_update_tracks`; snapshot counters | orchestration |

**Config fields (no magic numbers — CHARTER §4.5):**

| Field | Type | Default | Env binding | Meaning |
| ----- | ---- | ------- | ----------- | ------- |
| `enabled` | bool | `False` | `TRACKER_ENABLED` | Master gate; off = no tracker built, counters 0. |
| `backend` | str | `"norfair"` | `TRACKER_BACKEND` | Registry key of the tracker backend. |
| `distance_function` | str | `"euclidean"` | `TRACKER_DISTANCE_FUNCTION` | Norfair distance (euclidean = raw pixels). |
| `distance_threshold` | float | `20.0` | `TRACKER_DISTANCE_THRESHOLD` | Max association distance in **pixels** (`gt=0`). |
| `hit_counter_max` | int | `15` | `TRACKER_HIT_COUNTER_MAX` | Frames a track survives unmatched (`gt=0`). |
| `initialization_delay` | int | `3` | `TRACKER_INITIALIZATION_DELAY` | Frames before a track is confirmed + gets an id (`ge=0`). |

---

## 6. Wire / schema posture (backward compatibility)

**N/A — no wire change.** `jetson_yolo_gcs` has no `meshsa` wire envelope; no `schema_version` is
involved. The frozen `Detection` gains **no** field (the id rides on the local `TrackedDetection`
wrapper). Snapshot gains additive local diagnostic keys.

---

## 7. Test plan (by category)

Fakes-first, no hardware. **Coverage floor: 96%** (`jetson_yolo_gcs`); the only `# pragma: no
cover` are the real `norfair`/`numpy` construction seams and `build_pipeline` device wiring.

- **Unit** — `TrackerBase` default `close`; registry dispatch + duplicate/unknown + lazy norfair
  registration (fake backend); `NorfairTracker` id map-back, `id is None` skip, empty result, close
  (injected fake tracker + identity `to_detections`); `TrackerSettings` defaults + `TRACKER_*`
  overrides + `ValidationError` on out-of-range.
- **Integration / behavioural** — pipeline with a scripted fake tracker: counters track a persistent
  object (`tracks_active==1`, `tracks_total==1`) and a second appearing object (`tracks_total==2`);
  a raising tracker → `dropped_tracks` increments over two frames (log-throttle branches) and the
  loop survives; **selection-unchanged pin**: the published target is identical with the tracker on
  vs off.
- **Import-cleanliness** — `norfair` absent from `sys.modules` after `import jetson_yolo_gcs`.

---

## 8. Exit criteria

- **Mechanism (met):** §7 green; `ruff` / `ruff format` / `mypy --strict` / `pytest` green; coverage
  ≥96% (99.3% measured); CHANGELOG + NEXTSTEPS updated; status → `Implemented`.
- **Validation (separate, pending):** on-device run with a real Norfair-tracked camera feed
  observing stable ids and confirming `numpy<2` co-installs cleanly with the chosen inference extra
  (`[ultralytics]`/`[hailo]`) on the target Jetson image → status `Validated`. Thresholds
  (`distance_threshold`, `initialization_delay`) stay provisional until tuned on real footage.

---

## 9. CHARTER §4 invariant checklist

| # | Invariant | How this design preserves it |
|---|-----------|------------------------------|
| 1 | Open/closed registry extensibility | Backends register via `@tracker_registry.register`; the pipeline dispatch is not edited per backend. |
| 2 | Versioned, backward-compatible wire | N/A — no meshsa wire; frozen `Detection` unchanged (§6). |
| 3 | DI via `Protocol`/seams, tests need no hardware | Injected `tracker`; injectable `tracker`/`to_detections` seams; fakes-only tests. |
| 4 | Stateful I/O in transports/services, not codecs | Track state lives in the tracker/backend; no codec involved; no vehicle I/O. |
| 5 | Config-driven, no magic numbers | All tuning is `TRACKER_*` config with explicit defaults (§5). |
| 6 | Gates green; hardware glue is the only `# pragma: no cover` | 99.3% coverage; only real norfair/numpy + device wiring excluded. |
| 7 | No secrets / machine fingerprints | None introduced. |
