"""Versioning and wire-schema compatibility policy.

Backward compatibility is anchored here: every Envelope carries ``schema_version``
and peers accept any version in ``[MIN_COMPATIBLE_SCHEMA, SCHEMA_VERSION]``.
"""

from __future__ import annotations

__version__ = "0.1.0"

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
