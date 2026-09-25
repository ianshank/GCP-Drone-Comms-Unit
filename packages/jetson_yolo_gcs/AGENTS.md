# AGENTS.md — `jetson_yolo_gcs`

Scoped guide for the on-board perception package (camera → YOLO/Hailo detection →
GStreamer video to a GCS → opt-in MAVLink `LANDING_TARGET`). Read the repo-root
`AGENTS.md` / `docs/CHARTER.md` first; this file covers package-local conventions.

## Layout

- `core/` — `config` (pydantic-settings v2), `logging` (structlog), `clock`, `registry`, `errors`.
- `detection/` — `DetectorBase` ABC + frozen result types; `factory` routes a model file to a
  backend **by extension**; `ultralytics_backend` (`.pt`/`.engine`/`.onnx`), `hailo_backend` (`.hef`, stub).
- `streaming/` — `camera` (capture pipeline builder + `CameraSource` seam) and `gstreamer`
  (egress pipeline builder + `StreamWriter` seam).
- `mavlink/bridge.py` — `LandingTargetBridge` (pymavlink; injectable connection).
- `pipeline.py` — DI-assembled orchestrator; `build_pipeline` wires real devices (`# pragma: no cover`).
- `cli.py` — `--health-check`, `export-model`, default `run`.

## Traps

- **This is a second, independent distribution.** Its own `pyproject.toml`, its own
  coverage floor (**96**, not meshsa's 97), and its own gates, which run *from this
  directory*. Running the repo-root commands does not check this package.
- **`meshsa` is not importable from here, by design.** Reaching for a meshsa helper is
  the single easiest way to break this package: it works locally and fails
  `tests/unit/test_imports_clean.py::test_package_does_not_import_meshsa`. Where
  behavior must match, it is *re-implemented* deliberately — `mavlink/heartbeat.py`
  mirrors `meshsa.command.health`, `geometry/ned.py` mirrors
  `meshsa.cv.geo.project_to_ground`, and both say so in their docstrings. Every
  `meshsa` mention in `src/` is prose explaining the deliberate non-import; there is no
  import to copy from.
- **`numpy` is confined to the optional Norfair tracker backend.** It is not in
  `[project.dependencies]`; it arrives only as a lazy, `[tracker]`-extra-gated transitive
  dependency of `norfair`, which pins `numpy<2`. `geometry/ned.py` is deliberately
  pure-Python math. A `import numpy` anywhere else is a regression, not an optimization.
- **`detection/factory.py` routes by file extension.** A new backend needs both the
  registry decorator *and* an `_EXTENSION_BACKENDS` entry; register only one and the
  model file silently routes to the wrong backend or none.
- **The four failure paths below are deliberately different from each other.** The
  recurring mistake is collapsing them into one `try/except` — see the section's own
  warning, and note that `LANDING_TARGET` is the safety write path.
- **`FpsCounter.fps` advances only on successful frames**, so during a sustained stall
  it keeps reporting the last good rate. It is not a liveness signal.

## Conventions (keep these invariant)

1. **No magic numbers.** Every environment-varying value is a `*Settings` field with an
   explicit default and an env prefix: `YOLO_`, `CAMERA_`, `STREAM_`, `MAVLINK_`, `TRACKER_`,
   `PIPELINE_`, `APP_`. Fixed protocol/codec constants (RTP payload type, encoder tuning) are
   named module constants, **not** config. Add new operator-tunable values to config, not as
   literals — why: these run on field hardware that is reconfigured by environment, never by
   edit-and-redeploy — control: `literal_guard` (`tools/claude_hooks/`).
2. **DI via Protocols/seams.** `CameraSource`, `StreamWriter`, `DetectorBase`, the injectable
   pymavlink connection, and injectable `clock`/`sleep` mean unit tests use fakes and need **no**
   GPU/camera/autopilot. Only real device/encoder/model construction is `# pragma: no cover`
   — why: without the seams the suite would need a Jetson, so it would not run in CI at all
   — control: the 96% coverage floor, which `# pragma: no cover` on the device path is what
   makes reachable.
3. **Lazy hardware imports.** `ultralytics`/`cv2`/`pymavlink`/`hailo_platform`/`norfair`/`numpy`
   import *inside* factories, never at module top, so `import jetson_yolo_gcs` stays light
   (locked by `tests/unit/test_imports_clean.py`). **`numpy` is confined to the optional Norfair
   tracker backend** (`tracking/norfair_backend.py`) as a lazy, `[tracker]`-extra-gated transitive
   dep of `norfair`; it is never in `[project.dependencies]` and never used in the base package or
   the pure math (`geometry/ned.py` stays no-numpy). numpy anywhere else is a regression
   — why: a top-level hardware import makes `--health-check` fail on any host without the
   accelerator, which is every CI runner
   — control: `tests/unit/test_imports_clean.py::test_package_import_is_light`.
4. **Add a detector backend via the registry**, never by editing the factory: implement
   `DetectorBase`, register a factory with `@detector_registry.register("name")`, and add the
   file extension to `_EXTENSION_BACKENDS` in `detection/factory.py` — why: the factory is the
   dispatch point every backend shares, so editing it for one backend is how a change to one
   reaches all of them.
5. **Self-contained.** No runtime dependency on `meshsa`; it stays usable as a standalone
   library — why: this package ships to the airframe while meshsa ships to the ground station,
   so a shared import would couple two independently-deployed distributions
   — control: `tests/unit/test_imports_clean.py::test_package_does_not_import_meshsa`.

## Pipeline loop failure policy (important)

`Pipeline.step()` handles failures **per path** — do not collapse this into one blanket catch:

- **Detection** — a recoverable `DetectionError` (malformed output) is dropped-and-counted
  (`dropped_detections`, rate-limited log) and the loop continues. Any *other* error (CUDA OOM,
  a real bug) **propagates** so it surfaces — why: a malformed frame is routine on a live
  camera, while CUDA OOM is a fault that must not be absorbed into a counter nobody reads.
- **Stream egress** — best-effort: a write failure is dropped-and-counted (`dropped_stream`)
  — why: video to the GCS is observability, not control; losing a frame must never stop
  detection or the safety write path.
- **Tracking** — advisory/read-only: an `update()` fault is dropped-and-counted (`dropped_tracks`)
  and the loop continues. The tracker feeds only the health snapshot (`tracks_active`/`tracks_total`)
  and **never** influences `LANDING_TARGET` target selection. Add a tracker backend via
  `@tracker_registry.register("name")` (like detector backends), never by editing the pipeline
  — why: the tracker is optional and `[tracker]`-extra-gated, so anything depending on it would
  change behaviour based on which extras are installed — advisory: the separation is held by
  the pipeline's structure and its tests, not by a checker.
- **`LANDING_TARGET` publish** — **tolerate-then-escalate**: a failed publish is counted and
  rate-limit-logged, and re-raises once *consecutive* failures exceed
  `publish_failure_tolerance` (default `3`; `0` fails loud on the first). A heartbeat-gate
  suppression is counted separately and does **not** reset the streak. This is the safety write
  path; silently never-publishing must never look healthy, but a single transient blip must not
  kill the camera+stream loop. Do not collapse this into a bare propagate — why: both failure
  modes are real safety faults in opposite directions, so neither a bare catch nor a bare
  propagate is correct — control: the tolerance boundary is asserted in the pipeline tests;
  note the predicate is `>` (*exceeds*), not `>=`.

`run()` tolerates transient empty reads (camera timeouts) and only stops after
`max_consecutive_empty` consecutive empties (`None` = run until `request_stop()`/SIGTERM).
Idle back-off is `PIPELINE_IDLE_POLL_S` (non-zero, avoids a CPU spin).

> Known limitation: `FpsCounter.fps` only advances on successful frames, so during a sustained
> stall it reports the last good rate. Don't treat `fps` as a liveness signal.

## Gates (run from this directory: `packages/jetson_yolo_gcs`)

```
ruff check . && ruff format --check . && python -m mypy src && python -m pytest
```

`mypy --strict` and ruff stay clean; the suite is fakes-first and the coverage floor is **96%**
(actual typically ~99%). `jetson-yolo-gcs --health-check` must keep exiting 0 with no hardware.
