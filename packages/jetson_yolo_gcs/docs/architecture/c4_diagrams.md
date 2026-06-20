# jetson-yolo-gcs — C4 architecture

C4 model (Context → Container → Component) for the on-board perception package. Mirrors
the diagram style of the repo-level [`docs/C4.md`](../../../../docs/C4.md).

## Level 1 — System context

```mermaid
C4Context
  title System context — jetson-yolo-gcs on a Jetson edge node
  Person(operator, "Operator", "Watches video / supervises landing in the GCS")
  System(jyg, "jetson-yolo-gcs", "On-board detection, video egress, LANDING_TARGET")
  System_Ext(camera, "Camera", "USB / CSI / RTSP source")
  System_Ext(gcs, "Ground Control Station", "QGroundControl video receiver")
  System_Ext(autopilot, "Autopilot", "MAVLink vehicle (precision-landing mode)")
  Rel(camera, jyg, "Frames", "v4l2 / GStreamer")
  Rel(jyg, gcs, "H.264 video", "RTP/UDP")
  Rel(jyg, autopilot, "LANDING_TARGET (advisory, opt-in)", "MAVLink")
  Rel(operator, gcs, "Views video / supervises")
```

## Level 2 — Containers

```mermaid
C4Container
  title Containers — jetson-yolo-gcs package
  Container(cli, "cli", "Python", "Entry point: --health-check, export-model, run")
  Container(pipeline, "pipeline", "Python", "Orchestrator: camera → detector → stream + mavlink")
  Container(detection, "detection", "Python", "DetectorBase + registry + ultralytics/hailo backends")
  Container(streaming, "streaming", "Python", "Camera source + GStreamer pipeline builders")
  Container(mavlink, "mavlink", "Python", "LANDING_TARGET publisher (pymavlink)")
  Container(core, "core", "Python", "config (pydantic-settings), logging, clock, registry")
  Rel(cli, pipeline, "builds & runs")
  Rel(pipeline, detection, "detect(frame)")
  Rel(pipeline, streaming, "read_frame / write")
  Rel(pipeline, mavlink, "publish(detection)")
  Rel(detection, core, "config / registry")
  Rel(streaming, core, "config")
  Rel(mavlink, core, "config / clock")
```

## Level 3 — Components (detection)

```mermaid
C4Component
  title Components — detection backend selection
  Component(factory, "build_detector", "func", "Maps model extension → backend via registry")
  Component(registry, "detector_registry", "Registry[DetectorBase]", "Open/closed backend registration")
  Component(base, "DetectorBase", "ABC", "detect() -> DetectionResult; frozen Detection dataclasses")
  Component(ultra, "UltralyticsDetector", "backend", ".pt / .engine / .onnx (lazy ultralytics)")
  Component(hailo, "HailoDetector", "backend (stub)", ".hef (lazy hailo_platform)")
  Rel(factory, registry, "create(name)")
  Rel(registry, ultra, "registers")
  Rel(registry, hailo, "registers")
  Rel(ultra, base, "implements")
  Rel(hailo, base, "implements")
```

## Level 4 — Code / key seams

- **Dependency-injection seams (Protocols):** `core.clock.Clock`,
  `streaming.camera.CameraSource`, `streaming.gstreamer.StreamWriter`, plus the injectable
  pymavlink connection on `mavlink.bridge.LandingTargetBridge`. Unit tests substitute fakes;
  the real OpenCV/ultralytics/pymavlink construction is the only `# pragma: no cover`.
- **Pure, testable builders:** `streaming.camera.build_capture_pipeline`,
  `streaming.gstreamer.build_stream_pipeline`, `mavlink.bridge.compute_angles`,
  `utils.fps.FpsCounter`, `utils.jetson.parse_tegrastats`, and `cli.health_report`.
- **Config:** `core.config.Settings` composes `YoloSettings` / `CameraSettings` /
  `StreamSettings` / `MavlinkSettings`, each a `pydantic-settings` `BaseSettings` with its own
  env prefix. `MavlinkSettings.enable_landing_target` defaults to **false**.
