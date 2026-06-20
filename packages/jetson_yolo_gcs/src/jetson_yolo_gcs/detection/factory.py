"""Detector factory: pick a backend from the model file extension.

Backends self-register on :data:`detector_registry` (open/closed — adding a backend
never edits this module). :func:`build_detector` maps the model file's extension to a
registered backend name, then asks the registry to build it. The backend modules are
imported lazily inside :func:`build_detector` so importing this module never pulls a
heavy inference dependency.
"""

from __future__ import annotations

from pathlib import Path

from ..core.config import YoloSettings
from ..core.errors import UnknownBackendError
from ..core.registry import Registry
from .base import DetectorBase

#: Registry of detection backends keyed by backend name.
detector_registry: Registry[DetectorBase] = Registry("detector")

#: Model file extension -> backend name. Adding a format is a one-line change here.
_EXTENSION_BACKENDS: dict[str, str] = {
    ".pt": "ultralytics",
    ".engine": "ultralytics",
    ".onnx": "ultralytics",
    ".hef": "hailo",
}


def backend_for_path(model_path: str) -> str:
    """Return the backend name for a model file, by extension.

    Raises :class:`UnknownBackendError` for an unrecognised extension.
    """
    ext = Path(model_path).suffix.lower()
    try:
        return _EXTENSION_BACKENDS[ext]
    except KeyError as exc:
        known = ", ".join(sorted(_EXTENSION_BACKENDS))
        raise UnknownBackendError(
            f"no detection backend for model {model_path!r} (extension {ext!r}); known: {known}"
        ) from exc


def build_detector(settings: YoloSettings, *, backend: str | None = None) -> DetectorBase:
    """Build a detector for ``settings.model_path`` (or an explicit ``backend``)."""
    # Import backends here (not at module top) to trigger registration without
    # pulling ultralytics/hailo at package import time.
    from . import hailo_backend as _hailo  # noqa: F401
    from . import ultralytics_backend as _ultra  # noqa: F401

    name = backend or backend_for_path(settings.model_path)
    return detector_registry.create(name, settings=settings)
