"""Import-time architectural gates for the package.

Two distinct invariants, kept in separate tests because they fail for different
reasons: heavy/hardware dependencies must stay lazy, and this distribution must not
acquire a runtime dependency on ``meshsa``.

Both run the import in a **fresh subprocess**, which is the whole trick. The obvious
in-process form — pop the modules from ``sys.modules``, re-import the package, assert
they did not come back — does not work here and silently passes:
``tests/conftest.py`` imports ``jetson_yolo_gcs.detection.base`` at collection time,
so the package is already cached by the time any test body runs. Popping the
*dependency* and re-importing the *package* is then a no-op, the dependency never
reappears, and the assertion holds no matter what the package imports.

That is not hypothetical. The in-process form of the meshsa gate was committed on this
branch, and adding ``import meshsa`` to ``src/jetson_yolo_gcs/__init__.py`` left the
whole file passing. A gate that cannot fail is worse than no gate, because its green
line is read as evidence.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

#: Hardware and heavy-compute modules that must only be imported inside factories, so
#: ``import jetson_yolo_gcs`` and ``jetson-yolo-gcs --health-check`` work on a host with
#: no accelerator — which is every CI runner.
HEAVY_MODULES = ("ultralytics", "cv2", "pymavlink", "hailo_platform", "norfair", "numpy")

#: The sibling distribution this package must stay independent of.
FORBIDDEN_ROOT = "meshsa"

#: Seconds allowed for the probe interpreter. Importing this package is sub-second by
#: design; a timeout here is itself a signal that something heavy crept in.
PROBE_TIMEOUT_S = 120


def _modules_present_after_import(prefixes: tuple[str, ...]) -> list[str]:
    """Import the package in a fresh interpreter; return which *prefixes* got loaded.

    A prefix matches its own name and its submodules, so ``meshsa`` also catches
    ``meshsa.command.health``.
    """
    probe = textwrap.dedent("""
        import json, sys
        prefixes = json.loads(sys.argv[1])
        import jetson_yolo_gcs  # noqa: F401
        found = sorted(
            name
            for name in sys.modules
            if any(name == p or name.startswith(p + ".") for p in prefixes)
        )
        print(json.dumps(found))
    """)
    import json

    result = subprocess.run(
        [sys.executable, "-I", "-c", probe, json.dumps(list(prefixes))],
        capture_output=True,
        text=True,
        timeout=PROBE_TIMEOUT_S,
        check=True,
    )
    return list(json.loads(result.stdout))


def test_probe_can_detect_a_loaded_module() -> None:
    """The probe reports a module that *is* loaded — so a pass means something.

    Without this, both gates below would be indistinguishable from a probe that always
    returns an empty list, and that is precisely the failure mode this file exists to
    rule out. ``json`` is imported by the probe itself and by the standard library's
    own machinery, so it is always present.

    Note that none of :data:`HEAVY_MODULES` is installed in a normal dev or CI
    environment — they arrive only with the optional extras on a device image — so a
    mutation test against them cannot run here. This asserts the mechanism instead.
    """
    found = _modules_present_after_import(("json",))
    assert "json" in found
    # Submodules match the prefix too, which is what makes `meshsa` catch
    # `meshsa.command.health`.
    assert any(name.startswith("json.") for name in found), found


def test_package_import_is_light() -> None:
    """No hardware or heavy-compute module is imported at package import time."""
    leaked = _modules_present_after_import(HEAVY_MODULES)
    assert leaked == [], f"imported at package import time: {leaked}"


def test_package_does_not_import_meshsa() -> None:
    """`jetson_yolo_gcs` ships to the airframe; `meshsa` ships to the ground station.

    The two are deployed independently, so a shared import would couple their release
    cycles. Several modules here deliberately re-implement a meshsa behaviour rather
    than import it (`mavlink/heartbeat.py` mirrors `meshsa.command.health`,
    `geometry/ned.py` mirrors `meshsa.cv.geo.project_to_ground`), and each says so in
    its docstring. Reaching for the real thing works locally and must fail here.
    """
    leaked = _modules_present_after_import((FORBIDDEN_ROOT,))
    assert leaked == [], f"{FORBIDDEN_ROOT} was imported at package import time: {leaked}"
