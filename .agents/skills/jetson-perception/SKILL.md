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
- Planned hardening (plan Track C.1, spec `docs/specs/initiative-d-perception.md`):
  **≥10 Hz cadence floor + stale-target suppression**, and a reconsidered in-flight
  publish-failure policy. Add config fields (e.g. `MAVLINK_MIN_RATE_HZ`,
  `MAVLINK_TARGET_STALE_S`) — no literals. Tighten coverage on `pipeline.py` + `mavlink/bridge.py`.
  The autopilot **heartbeat gate** (fail-closed) is already shipped (below) and guards both
  send paths.

### Frame-dispatched LANDING_TARGET + PX4 LOCAL_NED (Tier 3)

- `mavlink/bridge.py` dispatches on config `frame` (`MAVLINK_FRAME`, `Literal["body_frd",
  "local_ned"]`, default `body_frd`). `body_frd` is the original angular-offset publish path —
  **byte-identical wire output**, pin-guarded by tests; never change it incidentally while
  touching the `local_ned` path.
- `local_ned` (`_MAV_FRAME_LOCAL_NED`) projects a pixel to a North/East/Down offset and sends
  `position_valid=1`. It depends on two injectable seams, both required, both fail-safe when
  absent:
  - `geometry/ned.py::project_pixel_to_ned(cam, cx, cy, *, alt_agl_m, heading_deg, pitch_deg,
    roll_deg=0.0) -> NedOffset | None` — pure, **no-numpy**, hardware-free flat-ground ray-cast
    (mirrors `meshsa.cv.geo`, but kept independent — `jetson_yolo_gcs` must never `import
    meshsa`). Returns `None` (never raises) for `alt_agl_m<=0`, degenerate `img_w`/`img_h<=0`,
    or a ray at/above the horizon.
  - `mavlink/pose.py::PoseSource` — a `runtime_checkable` `Protocol` (`latest() -> VehiclePose |
    None`) so the bridge unit-tests against a fake with **no** live autopilot link.
    `MavlinkPoseSource` is the real implementation: drains `ATTITUDE` + an injected AGL callable
    (rangefinder/`GLOBAL_POSITION_INT`) into a cached `VehiclePose`; a partial/failed poll leaves
    any previously cached pose untouched rather than clobbering it.
  - **Fail-safe rule:** no `PoseSource` configured, no fresh pose available, or an unprojectable
    ray (any of the above `None` cases) → `_send_local_ned` returns `False` and **nothing is
    sent** (a `position_valid=1` message with a bogus position is worse than silence). Same
    contract as a 0-dim/degenerate frame.
- **Reason-keyed suppression accounting** replaces the old single conflated counter:
  `_note_suppressed(reason, message, **fields)` increments a monotonic per-reason counter
  (`no_heartbeat` / `no_pose` / `unprojectable`) exposed via `suppressed_snapshot()`, and
  `pipeline.py::snapshot()` surfaces it as `landing_target_suppressed_by_reason` (the prior
  aggregate total is retained alongside it). Use this to tell a dead autopilot link apart from a
  missing/unprojectable pose.
- **TIMESYNC + capture-time `time_usec`:** `mavlink/timesync.py::TimeSync(offset_us=0)` +
  `to_vehicle_usec(local_s)` hold the local→vehicle clock offset; the actual device TIMESYNC
  round-trip (`TimeSync.exchange`) is hardware-only and `# pragma: no cover` (deferred — no
  hardware validation yet). Config: `MAVLINK_TIMESYNC_ENABLED` (bool, default `False`) is
  **load-bearing** — it gates whether the offset is applied at all, independent of whether a
  `TimeSync` is wired. `MAVLINK_CAPTURE_TIME_SOURCE` (`Literal["publish", "capture"]`, default
  `publish`) selects between the wall-clock-at-publish default and the per-frame capture
  timestamp (`capture_t`, same timebase as the injected clock) for `LANDING_TARGET.time_usec`.
- Named protocol constants, not magic numbers: `_MAV_FRAME_BODY_FRD=12`,
  `_MAV_FRAME_LOCAL_NED=1`, `_LANDING_TARGET_TYPE_LIGHT_BEACON=0`, `_IDENTITY_QUATERNION_WXYZ`
  (`(1.0, 0.0, 0.0, 0.0)`), `_USEC_PER_SEC` (in `timesync.py`, imported by `bridge.py` so the
  factor lives in exactly one place).
- Both new modules stay **meshsa-free and no-numpy** (repo-wide invariant) — `geometry/ned.py`
  uses only `math`/`dataclasses`.

## Gates (run from `packages/jetson_yolo_gcs`)

```
ruff check . && ruff format --check . && python -m mypy src && python -m pytest
```

Coverage floor **96%** (typically ~99%); `jetson-yolo-gcs --health-check` must exit 0 with no
hardware.

## References

- `packages/jetson_yolo_gcs/AGENTS.md` (conventions + failure policy)
- `packages/jetson_yolo_gcs/src/jetson_yolo_gcs/{detection,streaming,mavlink,pipeline}.py`
- `packages/jetson_yolo_gcs/src/jetson_yolo_gcs/geometry/ned.py` (pure NED projection)
- `packages/jetson_yolo_gcs/src/jetson_yolo_gcs/mavlink/{pose,timesync}.py` (injectable seams)
- `docs/specs/initiative-d-perception.md` (author from TEMPLATE before Track C work)
- `docs/CHARTER.md` §3 perception carve-out
