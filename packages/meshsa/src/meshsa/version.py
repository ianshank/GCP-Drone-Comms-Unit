"""Versioning and wire-schema compatibility policy.

Backward compatibility is anchored here: every Envelope carries ``schema_version``
and peers accept any version in ``[MIN_COMPATIBLE_SCHEMA, SCHEMA_VERSION]``.
"""

from __future__ import annotations

import warnings

__version__ = "0.2.0"

#: Wire schema this build emits.
SCHEMA_VERSION = 1
#: Oldest wire schema this build still accepts (raise only on breaking changes).
MIN_COMPATIBLE_SCHEMA = 1


def is_compatible(schema_version: int) -> bool:
    """Return True if a peer's ``schema_version`` is interoperable with us."""
    return MIN_COMPATIBLE_SCHEMA <= schema_version <= SCHEMA_VERSION


#: Default set of wire schemas a codec accepts on decode (the full compatibility
#: window). A codec can be constructed with a narrower/explicit set so multiple
#: codec versions can coexist on one node.
SUPPORTED_SCHEMAS: frozenset[int] = frozenset(range(MIN_COMPATIBLE_SCHEMA, SCHEMA_VERSION + 1))


def warn_deprecated(old: str, replacement: str, *, removed_in: str | None = None) -> None:
    """Emit a ``DeprecationWarning`` for a renamed/aliased field or option.

    Establishes the compatibility-warning convention referenced by
    ``CONTRIBUTING.md``: when a model field or config key is renamed, keep the
    old name working and call this so consumers get a migration signal instead
    of a silent break.
    """
    msg = f"{old!r} is deprecated; use {replacement!r}"
    if removed_in is not None:
        msg += f" (scheduled for removal in {removed_in})"
    warnings.warn(msg, DeprecationWarning, stacklevel=2)
