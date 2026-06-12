"""Import hygiene: ``import meshsa.fpv`` must work without the ``[fpv]`` extra.

meshsa CI installs only ``[dev]`` (no ``pyserial``/``pyarrow``). pytest imports
every ``test_*`` module at collection, so any top-level ``import serial`` /
``import pyarrow`` in the fpv tree — or transitively via ``meshsa.fpv``
re-exports — would error the whole suite. These tests lock that invariant in.
"""

from __future__ import annotations

import importlib


def test_import_meshsa_fpv_does_not_pull_optional_extras():
    import sys

    # Drop any already-imported optional deps so we observe a fresh import graph.
    for opt in ("serial", "pyarrow"):
        sys.modules.pop(opt, None)
    importlib.import_module("meshsa.fpv")
    # Importing the package must not have eagerly imported the hardware/parquet deps.
    assert "serial" not in sys.modules
    assert "pyarrow" not in sys.modules


def test_public_api_surface_is_importable():
    fpv = importlib.import_module("meshsa.fpv")
    for name in fpv.__all__:
        assert hasattr(fpv, name), name
