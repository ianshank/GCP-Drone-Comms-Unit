"""Opt-in bounded log ring for the console's log-tail panel (spec §5.4, design D-5).

A structlog *processor* appended at wiring time only when ``ui.log_ring_enabled=true`` —
disabled deployments run byte-identical logging. The ring is in-memory and bounded
(``deque(maxlen=...)``); it is a tail, not a log shipper: a restart clears it.

Disclosure posture: entries carry structured **scalars only** (timestamp, level, logger,
event, scalar bound values) and are served solely behind the console's bearer boundary.
Safety rests on the repo-wide no-secrets-in-logs discipline (CHARTER §4.7) — the ring
whitelists shapes, not content.
"""

from __future__ import annotations

import collections
import math
from collections.abc import MutableMapping
from typing import Any

from ..protocols import Clock, SystemClock

__all__ = ["LogRing", "VALID_LEVELS"]

#: structlog method names -> numeric severity (stdlib ``logging`` scale).
_LEVELS = {
    "debug": 10,
    "info": 20,
    "warn": 30,
    "warning": 30,
    "error": 40,
    "exception": 40,
    "critical": 50,
    "fatal": 50,
}

#: Severity assumed for an unknown method name: never silently drop an unknown-but-
#: possibly-severe event below the floor.
_UNKNOWN_LEVEL = 20

#: Accepted (case-insensitive) level names — the config-time validation contract
#: (``UIConfig.log_ring_level``) checks against this same set, so a bad level fails at
#: config parse, not at wiring time.
VALID_LEVELS: frozenset[str] = frozenset(_LEVELS)

_SCALAR_TYPES = (str, int, float, bool)

#: event_dict keys handled explicitly (not repeated as bound values).
_RESERVED_KEYS = frozenset({"event", "logger", "level", "timestamp"})


def _is_scalar(value: Any) -> bool:
    """JSON-safe scalar: NaN/inf floats are rejected — they are not valid JSON."""
    if isinstance(value, float):
        return math.isfinite(value)
    return value is None or isinstance(value, _SCALAR_TYPES)


class LogRing:
    """Bounded ring of structured scalar log entries with a level floor.

    ``processor`` is a standard structlog processor: it records a bounded copy of each
    passing event and returns the ``event_dict`` unchanged, so appending it never alters
    what the existing pipeline emits.
    """

    def __init__(self, size: int, level: str = "info", *, clock: Clock | None = None) -> None:
        if size <= 0:
            raise ValueError("log ring size must be > 0")
        if level.strip().lower() not in _LEVELS:
            raise ValueError(f"unknown log level {level!r}; expected one of {sorted(_LEVELS)}")
        self._floor = _LEVELS[level.strip().lower()]
        self._entries: collections.deque[dict[str, Any]] = collections.deque(maxlen=size)
        self._clock = clock or SystemClock()

    def processor(
        self, logger: Any, method_name: str, event_dict: MutableMapping[str, Any]
    ) -> MutableMapping[str, Any]:
        """structlog processor: capture scalar-only entries at/above the floor."""
        if _LEVELS.get(method_name, _UNKNOWN_LEVEL) >= self._floor:
            ts = event_dict.get("timestamp")
            entry: dict[str, Any] = {
                "ts": ts if isinstance(ts, int | float) else self._clock.now(),
                "level": method_name,
                "logger": event_dict.get("logger")
                if _is_scalar(event_dict.get("logger"))
                else None,
                "event": event_dict.get("event") if _is_scalar(event_dict.get("event")) else None,
            }
            for key, value in event_dict.items():
                if key not in _RESERVED_KEYS and _is_scalar(value):
                    entry[key] = value
            self._entries.append(entry)
        return event_dict

    def entries(self) -> list[dict[str, Any]]:
        """Newest-last bounded copy of the captured entries (satisfies ``LogSource``)."""
        return [dict(entry) for entry in self._entries]

    def install(self) -> None:
        """Prepend :meth:`processor` to the active structlog pipeline (opt-in wiring).

        Prepending (rather than appending) captures the event before any final renderer
        consumes it; the processor returns the ``event_dict`` unchanged, so the existing
        pipeline output is byte-identical.
        """
        import structlog

        current = structlog.get_config().get("processors", [])
        if self.processor not in current:
            structlog.configure(processors=[self.processor, *current])
