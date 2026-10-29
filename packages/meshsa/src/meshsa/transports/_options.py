"""Transport ``*Options`` models — the typed constructor surface (plan P2-4, CHARTER §4 Inv. 5).

Each transport used to take every tunable as a keyword argument: ``TakTcpTransport``
had 23, ``MeshtasticTransport`` 19. Those are not accidental — every one is a config
field with an explicit default — but a 23-parameter signature is unreadable, untestable
as a unit and impossible to pass around. The enterprise shape is a frozen dataclass per
transport (``TakTcpOptions``, ``MeshtasticOptions``, ``MspOptions``,
``MavlinkSourceOptions``) that the constructor accepts **alongside** the keyword form:

* ``TakTcpTransport(name, TakTcpOptions(host=..., port=...))`` — one object, typed;
* ``TakTcpTransport(name, host=..., port=...)`` — every existing call site, unchanged;
* ``TakTcpTransport(name, options, read_size=1)`` — a keyword overrides the model.

:func:`resolve_options` is the one place the two forms meet. Keywords that are not fields
of the model are returned separately as *extras*, which is how the hardware default
factories keep receiving their device-specific keys (``device``, ``baudrate``,
``connection``, ``endpoint``) exactly as before: the registry passes a transport's whole
config ``options`` dict through, and only the model's fields are lifted out of it.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from typing import Any, TypeVar, cast

__all__ = ["resolve_options"]

OptionsT = TypeVar("OptionsT")


def resolve_options(
    cls: type[OptionsT], options: OptionsT | None, overrides: Mapping[str, Any]
) -> tuple[OptionsT, dict[str, Any]]:
    """Merge an optional ``options`` model with keyword ``overrides``; split off extras.

    Returns ``(resolved, extras)``: ``resolved`` is ``options`` (or ``cls()`` when
    ``None``) with every override that names a field of ``cls`` applied on top (a keyword
    wins over the model, so a call site can take a shared model and tweak one field);
    ``extras`` are the overrides that are not fields, in their original order, for the
    transport's hardware factory. ``cls`` must be a dataclass.
    """
    names = {field.name for field in dataclasses.fields(cast(Any, cls))}
    known = {key: value for key, value in overrides.items() if key in names}
    extras = {key: value for key, value in overrides.items() if key not in names}
    base = options if options is not None else cls()
    resolved = cast(OptionsT, dataclasses.replace(cast(Any, base), **known)) if known else base
    return resolved, extras
