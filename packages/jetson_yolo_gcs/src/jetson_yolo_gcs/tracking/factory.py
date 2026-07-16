"""Tracker factory: build a tracker backend by name from settings.

Backends self-register on :data:`tracker_registry` (open/closed — adding a backend never
edits this module, mirroring :mod:`jetson_yolo_gcs.detection.factory`). The backend module
is imported lazily inside :func:`build_tracker` so importing this module never pulls the
heavy inference/tracking deps (``norfair``/``numpy``/``scipy``).
"""

from __future__ import annotations

from ..core.config import TrackerSettings
from ..core.registry import Registry
from .base import TrackerBase

#: Registry of tracker backends keyed by backend name.
tracker_registry: Registry[TrackerBase] = Registry("tracker")


def build_tracker(settings: TrackerSettings, *, backend: str | None = None) -> TrackerBase:
    """Build a tracker for ``settings`` (or an explicit ``backend`` name).

    Raises :class:`~jetson_yolo_gcs.core.errors.UnknownComponentError` for an unregistered
    backend name.
    """
    # Import the backend here (not at module top) to trigger registration without pulling
    # norfair/numpy at package import time.
    from . import norfair_backend as _norfair  # noqa: F401

    name = backend or settings.backend
    return tracker_registry.create(name, settings=settings)
