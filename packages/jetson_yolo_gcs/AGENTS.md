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

## Conventions (keep these invariant)

1. **No magic numbers.** Every environment-varying value is a `*Settings` field with an
   explicit default and an env prefix: `YOLO_`, `CAMERA_`, `STREAM_`, `MAVLINK_`, `TRACKER_`,
   `PIPELINE_`, `APP_`. Fixed protocol/codec constants (RTP payload type, encoder tuning) are
   named module constants, **not** config. Add new operator-tunable values to config, not as literals.
2. **DI via Protocols/seams.** `CameraSource`, `StreamWriter`, `DetectorBase`, the injectable
   pymavlink connection, and injectable `clock`/`sleep` mean unit tests use fakes and need **no**
   GPU/camera/autopilot. Only real device/encoder/model construction is `# pragma: no cover`.
3. **Lazy hardware imports.** `ultralytics`/`cv2`/`pymavlink`/`hailo_platform` import *inside*
   factories, never at module top, so `import jetson_yolo_gcs` stays light
   (locked by `tests/unit/test_imports_clean.py`).
4. **Add a detector backend via the registry**, never by editing the factory: implement
   `DetectorBase`, register a factory with `@detector_registry.register("name")`, and add the
   file extension to `_EXTENSION_BACKENDS` in `detection/factory.py`.
5. **Self-contained.** No runtime dependency on `meshsa`; it stays usable as a standalone library.

## Pipeline loop failure policy (important)

`Pipeline.step()` handles failures **per path** — do not collapse this into one blanket catch:

- **Detection** — a recoverable `DetectionError` (malformed output) is dropped-and-counted
  (`dropped_detections`, rate-limited log) and the loop continues. Any *other* error (CUDA OOM,
  a real bug) **propagates** so it surfaces.
- **Stream egress** — best-effort: a write failure is dropped-and-counted (`dropped_stream`).
- **Tracking** — advisory/read-only: an `update()` fault is dropped-and-counted (`dropped_tracks`)
  and the loop continues. The tracker feeds only the health snapshot (`tracks_active`/`tracks_total`)
  and **never** influences `LANDING_TARGET` target selection. Add a tracker backend via
  `@tracker_registry.register("name")` (like detector backends), never by editing the pipeline.
- **`LANDING_TARGET` publish** — **fails loud**: exceptions propagate and stop the run. This is
  the safety write path; silently never-publishing must never look healthy.

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
