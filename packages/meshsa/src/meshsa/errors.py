"""Framework exception hierarchy."""

from __future__ import annotations


class MeshSAError(Exception):
    """Base class for all framework errors."""


class IncompatibleSchemaError(MeshSAError):
    """Raised when a decoded Envelope uses an unsupported wire schema."""


class UnknownComponentError(MeshSAError, KeyError):
    """Raised when a registry has no factory for the requested name."""


class DuplicateRegistrationError(MeshSAError, ValueError):
    """Raised when registering a component name that already exists."""
