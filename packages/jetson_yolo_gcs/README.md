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
| MAVLink | `pymavlink` `LANDING_TARGET` publisher — **advisory, disabled by default**; never arms or flies |
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

## Architecture

See [`docs/architecture/c4_diagrams.md`](docs/architecture/c4_diagrams.md) for the C4
context/container/component views.
