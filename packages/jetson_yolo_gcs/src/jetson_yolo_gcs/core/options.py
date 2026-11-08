"""Dataclass-options resolution for keyword-compatible constructors.

Mirrors ``meshsa.transports._options.resolve_options`` deliberately — this package does
not import ``meshsa`` (see ``AGENTS.md``) — so a constructor can accept one typed options
object **or** the keyword form every existing call site uses, with a keyword overriding
one field of the object. Unlike the meshsa variant there are no "extras": a keyword that
names no field of any accepted model is a ``TypeError``, exactly as it was for the
keyword-only constructors this replaces.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from typing import Any, TypeVar, cast

__all__ = ["field_names", "resolve_options"]

OptionsT = TypeVar("OptionsT")


def field_names(cls: type[Any]) -> frozenset[str]:
    """The field names of dataclass ``cls``."""
    return frozenset(field.name for field in dataclasses.fields(cls))


def resolve_options(
    cls: type[OptionsT], options: OptionsT | None, overrides: Mapping[str, Any]
) -> OptionsT:
    """``options`` (or ``cls(**overrides)`` when ``None``) with ``overrides`` applied on top.

    Every key of ``overrides`` must be a field of ``cls``; the caller has already split
    off keys meant for another model. With ``options`` given, ``overrides`` are applied via
    ``dataclasses.replace`` (a keyword wins over the object); without it they are the
    constructor arguments, so required fields must be among them.
    """
    if options is None:
        return cls(**overrides)
    if not overrides:
        return options
    return cast(OptionsT, dataclasses.replace(cast(Any, options), **overrides))
