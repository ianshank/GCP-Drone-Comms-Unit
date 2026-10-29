"""Declarative environment-variable loader for the Pydantic config models (design D-11).

Every ``MESHSA_*`` binding used to be a hand-written ``(env key, field, caster)`` triple —
six copy-pasted section blocks in ``NodeConfig.from_env``, another in ``llm/server.py``, ad
hoc ``_env``/``_env_int`` helpers in ``cli.py``. The key was mechanical every time
(``<prefix><SECTION>_<FIELD>``) and the caster followed from the field's annotation, so the
triples were pure duplication of the model, and they drifted: a new field was silently
unbindable until someone remembered the table.

This module derives both from the model. A section declares *which* model binds under
*which* name; the keys and casters follow. The few non-mechanical keys (``MESHSA_DRONE_UID``
for ``ServerConfig.drone_uid``) are ``aliases``; the few bounded parses (a port range) are
``casters`` overrides. ``tests/test_env_inventory.py`` pins the resulting key set so the
derivation cannot add or drop a binding unnoticed.

Casters take ``(env_key, raw)`` and raise ``ValueError`` naming the key, so a typo in a unit
file surfaces as ``MESHSA_HEALTH_PORT: expected an integer, got 'http'`` at startup.
"""

from __future__ import annotations

import enum
import json
import types
import typing
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from pydantic import BaseModel

from ._parsing import parse_float, parse_int

__all__ = [
    "Caster",
    "apply_overrides",
    "caster_for",
    "env_inventory",
    "env_key",
    "env_scalar",
    "load_sections",
    "merge_config_json",
    "parse_bool",
    "parse_csv",
    "parse_str",
    "parse_token",
]

#: ``(env_key, raw_value) -> value``; the env key is for the error message.
Caster = Callable[[str, str], Any]

_TRUE = ("true", "1", "yes")
_FALSE = ("false", "0", "no", "")


def parse_bool(name: str, raw: str) -> bool:
    """Parse a boolean from an env-var string.

    Raises ``ValueError`` for unrecognised inputs so typos like ``"ture"`` are surfaced at
    startup rather than silently defaulting to ``False``. An empty string is ``False``.
    """
    cleaned = raw.strip().lower()
    if cleaned in _TRUE:
        return True
    if cleaned in _FALSE:
        return False
    raise ValueError(f"{name}: expected a boolean, got {raw!r}")


def parse_str(_name: str, raw: str) -> str:
    """No-op caster: the env value is already the target type (Pydantic coerces enums/literals)."""
    return raw


def parse_token(_name: str, raw: str) -> str | None:
    """A bearer credential: stripped, and ``""``/whitespace → ``None`` (no credential).

    Mirrors ``meshsa._web.normalize_token`` for the models that have no field validator of
    their own; a whitespace secret from a here-doc must never count as configured.
    """
    return raw.strip() or None


def parse_csv(_name: str, raw: str) -> tuple[str, ...]:
    """A comma-separated env value as a tuple of trimmed, non-empty items."""
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def env_key(prefix: str, section: str | None, field_name: str) -> str:
    """The mechanical key: ``<prefix>[<SECTION>_]<FIELD>`` (``MESHSA_HEALTH_PORT``)."""
    section_part = f"{section.upper()}_" if section else ""
    return f"{prefix}{section_part}{field_name.upper()}"


def _unwrap_optional(annotation: Any) -> Any:
    """``X | None`` → ``X``; anything else unchanged. A wider union is left for the caller."""
    if typing.get_origin(annotation) not in (typing.Union, types.UnionType):
        return annotation
    members = [arg for arg in typing.get_args(annotation) if arg is not type(None)]
    return members[0] if len(members) == 1 else annotation


def caster_for(model: type[BaseModel], field_name: str) -> Caster:
    """The caster a field's annotation implies.

    ``bool`` → :func:`parse_bool`; ``int``/``float`` → the actionable numeric parsers;
    ``str``, ``Literal[...]`` and string enums → identity (Pydantic validates the value);
    ``tuple[str, ...]``/``frozenset[str]`` → comma-separated. ``X | None`` binds as ``X``
    (``None`` is not expressible in an environment). A nested model, list or dict raises
    ``TypeError`` — sections declare those explicitly through :func:`load_sections`.
    """
    annotation = _unwrap_optional(model.model_fields[field_name].annotation)
    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)
    if annotation is bool:
        return parse_bool
    if annotation is int:
        return parse_int
    if annotation is float:
        return parse_float
    if origin is typing.Literal or annotation is str:
        return parse_str
    if isinstance(annotation, type) and issubclass(annotation, enum.Enum):
        return parse_str
    if origin in (tuple, frozenset) and args and args[0] is str:
        return parse_csv
    raise TypeError(
        f"{model.__name__}.{field_name}: no env caster for {annotation!r}; "
        "nested models bind as sections, collections need an explicit caster"
    )


def apply_overrides(
    model: type[BaseModel],
    data: dict[str, Any],
    env: Mapping[str, str],
    *,
    prefix: str,
    section: str | None = None,
    fields: Iterable[str] | None = None,
    casters: Mapping[str, Caster] | None = None,
    aliases: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Apply every present env override for ``model``'s fields onto ``data``; return it.

    ``fields`` limits the bindable fields (default: all of ``model.model_fields``);
    ``aliases`` maps a field to an absolute, non-mechanical key; ``casters`` overrides the
    derived caster (bounded parses, a token normaliser). A key that is present in ``env`` is
    applied even when empty — each model decides what an empty value means (``UIConfig``
    normalises an empty token to ``None``; ``HealthConfig`` carries it verbatim).
    """
    aliases = aliases or {}
    casters = casters or {}
    for name in fields if fields is not None else model.model_fields:
        key = aliases.get(name) or env_key(prefix, section, name)
        if key in env:
            caster = casters.get(name) or caster_for(model, name)
            data[name] = caster(key, env[key])
    return data


def load_sections(
    data: dict[str, Any],
    env: Mapping[str, str],
    *,
    prefix: str,
    sections: Mapping[str, type[BaseModel]],
) -> dict[str, Any]:
    """Apply ``<prefix><SECTION>_<FIELD>`` overrides for every declared section.

    A section already present in ``data`` (from a JSON blob) is overlaid, never replaced;
    a section with no blob entry and no env override is left absent so the model's
    ``default_factory`` builds it.
    """
    for section, model in sections.items():
        values = apply_overrides(
            model, dict(data.get(section, {})), env, prefix=prefix, section=section
        )
        if values:
            data[section] = values
    return data


def merge_config_json(
    data: dict[str, Any], env: Mapping[str, str], *, prefix: str
) -> dict[str, Any]:
    """Merge a ``<prefix>CONFIG_JSON`` blob into ``data`` (a full nested override); return it.

    Applied first, so individual scalar overrides win over the blob.
    """
    blob = env.get(f"{prefix}CONFIG_JSON")
    if blob:
        data.update(json.loads(blob))
    return data


def env_inventory(
    prefix: str,
    *,
    top_level: Iterable[str] = (),
    sections: Mapping[str, type[BaseModel]] | None = None,
    aliases: Mapping[str, str] | None = None,
) -> list[str]:
    """Every key a loader built from these declarations honours, in a stable order.

    The golden inventory test compares this against a hand-pinned list, so a field added
    to a section model shows up as a *declared* new binding rather than a silent one.
    """
    aliases = aliases or {}
    keys = [f"{prefix}CONFIG_JSON"]
    keys.extend(aliases.get(name) or env_key(prefix, None, name) for name in top_level)
    for section, model in (sections or {}).items():
        keys.extend(env_key(prefix, section, name) for name in model.model_fields)
    return keys


def env_scalar(env: Mapping[str, str], key: str, default: Any, caster: Caster = parse_str) -> Any:
    """``env[key]`` cast, or ``default`` when the key is absent (an entry-point flag default)."""
    raw = env.get(key)
    return default if raw is None else caster(key, raw)
