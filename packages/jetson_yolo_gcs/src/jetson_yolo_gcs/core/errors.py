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
