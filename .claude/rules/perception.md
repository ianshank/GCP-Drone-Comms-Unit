---
paths:
  - "packages/jetson_yolo_gcs/**/*.py"
---

# jetson_yolo_gcs perception

Fires anywhere in the perception distribution. Full context is in
[packages/jetson_yolo_gcs/AGENTS.md](packages/jetson_yolo_gcs/AGENTS.md).

## Rules

- Do not import `meshsa` from this package, in source or in tests — why: this
  distribution ships to the airframe and `meshsa` ships to the ground station, so a
  shared import couples two independently-deployed release cycles; where behaviour must
  match it is re-implemented deliberately (`mavlink/heartbeat.py`, `geometry/ned.py`)
  — control:
  `packages/jetson_yolo_gcs/tests/unit/test_imports_clean.py::test_package_does_not_import_meshsa`.
- Import `ultralytics`, `cv2`, `pymavlink`, `hailo_platform`, `norfair` and `numpy`
  inside factories, never at module top — why: a top-level hardware import makes
  `jetson-yolo-gcs --health-check` fail on any host without the accelerator, which is
  every CI runner — control:
  `packages/jetson_yolo_gcs/tests/unit/test_imports_clean.py::test_package_import_is_light`.
- Keep `numpy` confined to the Norfair tracker backend — why: it is a lazy,
  `[tracker]`-extra-gated transitive dependency of `norfair` (which pins `numpy<2`),
  not a declared dependency of this package; `geometry/ned.py` is deliberately
  pure-Python math, and numpy anywhere else is a regression rather than an
  optimisation.
- Keep the four pipeline failure paths distinct — detection drop-and-count with other
  errors propagating, stream best-effort, tracking advisory, `LANDING_TARGET`
  tolerate-then-escalate — why: they are deliberately different because the right
  answer differs per path; collapsing them into one `try/except` is the recurring
  mistake this section exists to prevent.
- Do not convert the `LANDING_TARGET` publish to a bare catch or a bare propagate
  — why: this is the safety write path, and both failure directions are real — silently
  never publishing must not look healthy, and one transient blip must not kill the
  camera and stream loop — control: the tolerance boundary is asserted in
  `packages/jetson_yolo_gcs/tests/integration/test_pipeline_mock.py`; note the predicate
  is `>` (*exceeds* `publish_failure_tolerance`, default `3`), not `>=`.
- Register a new detector or tracker backend through its registry, and add the file
  extension to `_EXTENSION_BACKENDS`, rather than editing the factory — why: the
  factory dispatches for every backend, so editing it for one is how a change to one
  reaches all of them; registering without the extension entry silently routes the
  model file nowhere.
- Add operator-tunable values as `*Settings` fields with an env prefix, not as literals;
  keep fixed protocol constants as named module constants — why: field hardware is
  reconfigured by environment, never by edit-and-redeploy — control: `literal_guard`
  (`tools/claude_hooks/literal_guard.py`).
- Do not treat `FpsCounter.fps` as a liveness signal — why: it only advances on
  successful frames, so a sustained stall keeps reporting the last good rate.
