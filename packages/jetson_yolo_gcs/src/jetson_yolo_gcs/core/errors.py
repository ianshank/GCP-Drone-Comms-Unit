"""Exception hierarchy for the perception package.

Rooted at :class:`JetsonYoloError` so callers can catch the whole family. Mirrors
the ``meshsa.errors`` pattern (a single base + specific subclasses for registry
lookups and config problems).
"""

from __future__ import annotations


class JetsonYoloError(Exception):
    """Base class for all errors raised by this package."""


class DuplicateRegistrationError(JetsonYoloError):
    """A component name was registered twice in a :class:`Registry`."""


class UnknownComponentError(JetsonYoloError):
    """A :class:`Registry` lookup found no component for the given key."""


class UnknownBackendError(JetsonYoloError):
    """No detection backend matches the model file (e.g. unknown extension)."""


class ConfigError(JetsonYoloError):
    """A configuration value is missing or invalid."""


class DetectionError(JetsonYoloError):
    """A detector failed to produce a usable result for a frame.

    Raised for *recoverable* per-frame failures (e.g. malformed model output). The
    pipeline catches this specifically, drops the frame, and continues — unexpected
    errors (CUDA OOM, programming bugs) are deliberately *not* wrapped so they surface.
    """


class MavlinkError(JetsonYoloError):
    """A MAVLink operation failed (e.g. no connection available to publish on)."""
