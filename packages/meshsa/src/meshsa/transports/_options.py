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

import structlog

__all__ = ["resolve_options"]

_log = structlog.get_logger("meshsa.transport")

OptionsT = TypeVar("OptionsT")

#: The constructor parameter that carries the model itself; a config dict naming it is
#: not an option of the transport.
_MODEL_KEY = "options"


def resolve_options(
    cls: type[OptionsT], options: OptionsT | None, overrides: Mapping[str, Any]
) -> tuple[OptionsT, dict[str, Any]]:
    """Merge an optional ``options`` model with keyword ``overrides``; split off extras.

    Returns ``(resolved, extras)``: ``resolved`` is ``options`` (or ``cls()`` when
    ``None``) with every override that names a field of ``cls`` applied on top (a keyword
    wins over the model, so a call site can take a shared model and tweak one field);
    ``extras`` are the overrides that are not fields, in their original order, for the
    transport's hardware factory. ``cls`` must be a dataclass.

    A key named ``options`` in ``overrides`` (a config file can carry one; the old
    constructors swallowed it with their ``**_``) is never forwarded, because the
    transport's ``options`` parameter already holds that name and a node must degrade on
    a stray key, not refuse to start: a ``cls`` instance is adopted as the base when no
    ``options`` was given, anything else is dropped with a warning.
    """
    if _MODEL_KEY in overrides:
        stray = overrides[_MODEL_KEY]
        overrides = {key: value for key, value in overrides.items() if key != _MODEL_KEY}
        if options is None and isinstance(stray, cls):
            options = stray
        else:
            _log.warning("transport_option_ignored", key=_MODEL_KEY, model=cls.__name__)
    names = {field.name for field in dataclasses.fields(cast(Any, cls))}
    known = {key: value for key, value in overrides.items() if key in names}
    extras = {key: value for key, value in overrides.items() if key not in names}
    base = options if options is not None else cls()
    resolved = cast(OptionsT, dataclasses.replace(cast(Any, base), **known)) if known else base
    return resolved, extras
