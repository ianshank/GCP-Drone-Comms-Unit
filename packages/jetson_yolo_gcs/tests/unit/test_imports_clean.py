"""Importing the package must not pull heavy/hardware deps (lazy-only)."""

from __future__ import annotations

import sys


def test_package_import_is_light() -> None:
    # Fresh import state for the optional heavy modules.
    for mod in ("ultralytics", "cv2", "pymavlink", "hailo_platform", "norfair", "numpy"):
        sys.modules.pop(mod, None)

    import jetson_yolo_gcs  # noqa: F401

    for mod in ("ultralytics", "cv2", "pymavlink", "hailo_platform", "norfair", "numpy"):
        assert mod not in sys.modules, f"{mod} was imported at package import time"
