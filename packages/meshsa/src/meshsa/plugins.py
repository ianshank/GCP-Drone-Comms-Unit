"""Out-of-tree transport/codec discovery via ``importlib.metadata`` entry points.

Third-party packages publish drivers under the ``meshsa.transports`` and
``meshsa.codecs`` entry-point groups; ``load_plugins()`` loads each entry point so
its import-time ``@transport_registry.register`` / ``@codec_registry.register``
runs. Opt-in — call it once at startup if you want to enable out-of-tree drivers
(it is intentionally not called implicitly so importing meshsa never imports
arbitrary third-party code).

Example (in a plugin's ``pyproject.toml``)::

    [project.entry-points."meshsa.transports"]
    halow = "my_pkg.halow"        # importing my_pkg.halow registers the transport
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

import structlog

_log = structlog.get_logger("meshsa.plugins")

TRANSPORT_GROUP = "meshsa.transports"
CODEC_GROUP = "meshsa.codecs"

EntryPointsFn = Callable[[str], Iterable[Any]]


def _stdlib_entry_points(group: str) -> Iterable[Any]:  # pragma: no cover - version shim
    """Select entry points for ``group`` across Python 3.10–3.12 metadata APIs."""
    from importlib import metadata

    eps = metadata.entry_points()
    select = getattr(eps, "select", None)
    if select is not None:  # py3.12+ selectable API
        return list(select(group=group))
    return list(eps.get(group, []))  # py3.10 dict-like


def load_plugins(
    groups: Iterable[str] = (TRANSPORT_GROUP, CODEC_GROUP),
    *,
    entry_points: EntryPointsFn | None = None,
) -> list[str]:
    """Load (import) registered plugins; return the entry-point names loaded.

    ``entry_points`` is injectable for testing; it defaults to the installed
    distribution metadata. A plugin that fails to load is logged and skipped so
    one broken driver never blocks the rest.
    """
    resolve = entry_points or _stdlib_entry_points
    loaded: list[str] = []
    for group in groups:
        for ep in resolve(group):
            try:
                ep.load()
            except Exception:
                _log.warning("failed to load plugin", group=group, name=getattr(ep, "name", "?"))
                continue
            loaded.append(ep.name)
            _log.info("loaded plugin", group=group, name=ep.name)
    return loaded
