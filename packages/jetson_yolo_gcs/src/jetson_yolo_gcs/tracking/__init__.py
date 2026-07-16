"""Multi-object tracking seam (detector output -> stable track ids).

This subpackage is deliberately light at import time: it exposes only the
:class:`~jetson_yolo_gcs.tracking.base.TrackerBase` abstraction and the
:class:`~jetson_yolo_gcs.tracking.base.TrackedDetection` value type. The Norfair
backend and its heavy deps (``norfair``/``numpy``/``scipy``) are imported lazily by
:func:`~jetson_yolo_gcs.tracking.factory.build_tracker`, so ``import jetson_yolo_gcs``
never pulls them (guarded by ``tests/unit/test_imports_clean.py``).

See ``docs/specs/initiative-d-perception.md`` (tracking section) for the design and the
read-only / no-LANDING_TARGET-influence safety posture.
"""

from __future__ import annotations

from .base import TrackedDetection, TrackerBase

__all__ = ["TrackedDetection", "TrackerBase"]
