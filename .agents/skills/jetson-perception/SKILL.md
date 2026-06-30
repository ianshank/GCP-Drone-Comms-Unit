---
name: jetson-perception
description: "Use when: working in packages/jetson_yolo_gcs — adding a detector backend (YOLO/Hailo/ONNX/TensorRT), GStreamer camera/egress pipeline, the MAVLink LANDING_TARGET bridge, precision-landing safety, or the perception pipeline failure policy."
argument-hint: "The perception change and which seam/backend it touches"
---

# Jetson Perception (`jetson_yolo_gcs`)

Self-contained on-board perception: camera → detection → GStreamer video to a GCS → opt-in,
advisory MAVLink `LANDING_TARGET`. **No runtime dependency on `meshsa`** — keep it standalone.
Read [../../../packages/jetson_yolo_gcs/AGENTS.md](../../../packages/jetson_yolo_gcs/AGENTS.md)
first; gates run from that directory.

## When to Use

- Adding/changing a detector backend, camera/egress pipeline, or the `LANDING_TARGET` bridge.
- Any change to `pipeline.py`, `mavlink/bridge.py`, or the precision-landing safety path.

## Procedure

1. **Add a detector via the registry, never by editing the factory:** implement `DetectorBase`,
   register with `@detector_registry.register("name")`, and add the file extension to
   `_EXTENSION_BACKENDS` in `detection/factory.py`.
2. **DI via seams:** `CameraSource`, `StreamWriter`, `DetectorBase`, the injectable pymavlink
   connection, and injectable `clock`/`sleep` mean tests use fakes and need **no**
   GPU/camera/autopilot. Only real device/encoder/model construction is `# pragma: no cover`.
3. **Lazy hardware imports:** import `ultralytics`/`cv2`/`pymavlink`/`hailo_platform` *inside*
   factories, never at module top (locked by `tests/unit/test_imports_clean.py`).
4. **No magic numbers:** every environment-varying value is a `*Settings` field with an explicit
   default and an env prefix (`YOLO_`, `CAMERA_`, `STREAM_`, `MAVLINK_`, `PIPELINE_`, `APP_`).
   Fixed protocol/encoder constants are named module constants, not config.
5. **Respect the per-path pipeline failure policy** (do not collapse into one catch):
   detection error → drop-and-count + continue; stream egress → best-effort drop-and-count;
   `LANDING_TARGET` publish → **fails loud**. Other errors (CUDA OOM, real bugs) propagate.

## Precision-landing safety (the write path — treat as critical)

- `LANDING_TARGET` is **advisory, opt-in, off by default**
  (`MAVLINK_ENABLE_LANDING_TARGET=false`). It never arms, sets modes, sends RC, or flies.
- Planned hardening (plan Track C.1, spec `docs/specs/initiative-d-perception.md`): autopilot
  **heartbeat gate** (fail-closed), **≥10 Hz cadence floor + stale-target suppression**, and a
  reconsidered in-flight publish-failure policy. Add config fields (e.g. `MAVLINK_MIN_RATE_HZ`,
  `MAVLINK_TARGET_STALE_S`) — no literals. Tighten coverage on `pipeline.py` + `mavlink/bridge.py`.

## Gates (run from `packages/jetson_yolo_gcs`)

```
ruff check . && ruff format --check . && python -m mypy src && python -m pytest
```

Coverage floor **85%** (typically ~98%); `jetson-yolo-gcs --health-check` must exit 0 with no
hardware.

## References

- `packages/jetson_yolo_gcs/AGENTS.md` (conventions + failure policy)
- `packages/jetson_yolo_gcs/src/jetson_yolo_gcs/{detection,streaming,mavlink,pipeline}.py`
- `docs/specs/initiative-d-perception.md` (author from TEMPLATE before Track C work)
- `docs/CHARTER.md` §3 perception carve-out
</content>
