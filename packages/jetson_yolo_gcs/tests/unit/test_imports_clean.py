"""Import-time architectural gates for the package.

Two distinct invariants, kept in separate tests because they fail for different
reasons: heavy/hardware dependencies must stay lazy, and this distribution must not
acquire a runtime dependency on ``meshsa``.
"""

from __future__ import annotations

import sys

HEAVY_MODULES = ("ultralytics", "cv2", "pymavlink", "hailo_platform", "norfair", "numpy")

#: The sibling distribution this package must stay independent of.
FORBIDDEN_ROOT = "meshsa"


def test_package_import_is_light() -> None:
    # Fresh import state for the optional heavy modules.
    for mod in HEAVY_MODULES:
        sys.modules.pop(mod, None)

    import jetson_yolo_gcs  # noqa: F401

    for mod in HEAVY_MODULES:
        assert mod not in sys.modules, f"{mod} was imported at package import time"


def test_package_does_not_import_meshsa() -> None:
    """`jetson_yolo_gcs` ships to the airframe; `meshsa` ships to the ground station.

    The two are deployed independently, so a shared import would couple their release
    cycles. Several modules here deliberately re-implement a meshsa behaviour rather
    than import it (`mavlink/heartbeat.py` mirrors `meshsa.command.health`,
    `geometry/ned.py` mirrors `meshsa.cv.geo.project_to_ground`), and each says so in
    its docstring. Reaching for the real thing works locally and must fail here.
    """
    for name in [
        m for m in sys.modules if m == FORBIDDEN_ROOT or m.startswith(f"{FORBIDDEN_ROOT}.")
    ]:
        sys.modules.pop(name, None)

    import jetson_yolo_gcs  # noqa: F401

    leaked = sorted(
        m for m in sys.modules if m == FORBIDDEN_ROOT or m.startswith(f"{FORBIDDEN_ROOT}.")
    )
    assert leaked == [], f"{FORBIDDEN_ROOT} was imported at package import time: {leaked}"
