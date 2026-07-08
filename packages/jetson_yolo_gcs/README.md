# jetson-yolo-gcs

On-board perception for a Jetson edge node: **YOLO/Hailo object detection → video
stream to a Ground Control Station (QGroundControl) → opt-in MAVLink `LANDING_TARGET`**
precision-landing guidance.

This package is part of the
[GCP-Drone-Comms-Unit](https://github.com/ianshank/GCP-Drone-Comms-Unit) monorepo
(see the perception carve-out in [`docs/CHARTER.md`](../../docs/CHARTER.md)), but it is
**self-contained** — it has no runtime dependency on `meshsa`, so it can be used as a
standalone dependency in other projects. It reuses meshsa's proven design (structlog
logging, a `Clock` Protocol, an open/closed `Registry`, and an injectable
`CameraSource`/`Frame` seam) by mirroring those small primitives.

## Design at a glance

| Concern | How |
|---|---|
| Config | `pydantic-settings` v2, per-domain env prefixes (`YOLO_`, `CAMERA_`, `STREAM_`, `MAVLINK_`); no hardcoded values |
| Detection backends | `DetectorBase` ABC + a registry; backend auto-selected by model extension (`.pt`/`.engine`/`.onnx` → Ultralytics, `.hef` → Hailo stub) |
| Camera / streaming | Pure GStreamer pipeline builders (USB/CSI/RTSP capture; `x264` CPU vs `nvv4l2` HW encode) behind injectable I/O seams |
| MAVLink | `pymavlink` `LANDING_TARGET` publisher — **advisory, disabled by default**; never arms or flies; `frame` selects `body_frd` (default) or opt-in PX4 `local_ned` |
| Testing | All hardware (GPU, camera, autopilot) is injected and faked; unit suite runs on a stock runner at ≥90% coverage |
| Import safety | `import jetson_yolo_gcs` pulls no heavy/hardware deps; ultralytics/opencv/pymavlink load lazily inside factories |

## First run

```bash
cd packages/jetson_yolo_gcs
cp .env.example .env          # edit YOLO_MODEL_PATH, CAMERA_*, STREAM_*, MAVLINK_* as needed
pip install -e ".[dev]"
jetson-yolo-gcs --health-check   # validates config + prints the resolved plan; no hardware
pytest                            # full unit + integration suite
```

For on-device use, add the runtime extras you need:

```bash
pip install -e ".[ultralytics,camera,mavlink]"   # YOLO + OpenCV/GStreamer + pymavlink
```

## LANDING_TARGET frame: `body_frd` (default) vs opt-in `local_ned`
`MavlinkSettings.frame` (env `MAVLINK_FRAME`, default `"body_frd"`) selects the wire shape of
the published `LANDING_TARGET`:
- **`body_frd` (default):** the original angular body-frame offsets. Byte-identical to prior
  releases — this path is pinned by test and does not change when `local_ned` is configured.
- **`local_ned` (opt-in):** projects the detection pixel onto a ground-relative North/East/Down
  offset (`geometry/ned.py::project_pixel_to_ned`, a pure/no-numpy flat-ground ray-cast mirroring
  `meshsa.cv.geo`) and sends it with `position_valid=1`. Needs two injected seams:
  - `mavlink.pose.PoseSource` (`runtime_checkable` Protocol, `latest() -> VehiclePose | None`) —
    `MavlinkPoseSource` reduces MAVLink `ATTITUDE` + an injected AGL reading into a
    `VehiclePose(alt_agl_m, heading_deg, pitch_deg, roll_deg=0.0)`.
  - `mavlink.timesync.TimeSync` (see below) for vehicle-clock-aligned timestamps.

  **Fail-safe suppression:** with no `PoseSource` wired, no fresh pose yet, or an unprojectable
  ray (non-positive AGL, degenerate image size, or a ray at/above the horizon), `publish()`
  returns `False` and **nothing is sent** — the bridge never fabricates a position. Suppression
  is reason-keyed (`_note_suppressed` / `suppressed_snapshot()`) as `no_heartbeat`, `no_pose`, or
  `unprojectable`, and `pipeline.py`'s `snapshot()` exposes the per-reason breakdown as
  `landing_target_suppressed_by_reason` (the aggregate total is unchanged). The existing
  fail-closed autopilot-heartbeat gate still guards both frame paths identically.

  `local_ned` is **advisory and opt-in** under the [`docs/CHARTER.md`](../../docs/CHARTER.md) §3
  perception carve-out — same as `body_frd`, it never arms, changes modes, or flies the aircraft.
  On-device hardware validation (real ATTITUDE stream + AGL source + PX4 consuming the frame) is
  still pending; today it is exercised end-to-end with fakes only.

## TIMESYNC + capture-time `LANDING_TARGET.time_usec`
Two independent config switches (both default to the pre-existing, unchanged behaviour):
- `MAVLINK_CAPTURE_TIME_SOURCE` (`capture_time_source`, `"publish"` default | `"capture"`) —
  `"publish"` stamps `time_usec` from the wall clock at send time (unchanged). `"capture"` stamps
  the frame's own capture timestamp instead, so `time_usec` reflects when the image was taken
  rather than when it was sent.
- `MAVLINK_TIMESYNC_ENABLED` (`timesync_enabled`, default `false`) — **only takes effect when
  `capture_time_source="capture"`.** When both are set, `mavlink.timesync.TimeSync.offset_us` is
  added to the capture timestamp (`to_vehicle_usec`) to align it to the vehicle's clock. The
  device-side MAVLink TIMESYNC round-trip that populates `offset_us` (`TimeSync.exchange`) is
  hardware-only and deferred (`# pragma: no cover`); `TimeSync` itself defaults `offset_us=0` (no
  offset applied) so it is safe to wire up ahead of that hardware work.

## Architecture

See [`docs/architecture/c4_diagrams.md`](docs/architecture/c4_diagrams.md) for the C4
context/container/component views.
