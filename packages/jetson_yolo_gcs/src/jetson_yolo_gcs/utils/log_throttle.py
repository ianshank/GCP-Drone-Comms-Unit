"""Shared rate-limited-logging predicate.

A single source of truth for the "log on the 1st occurrence and every Nth thereafter"
throttle used by the pipeline (dropped frames) and the MAVLink bridge (suppressed
publishes), so a persistent fault never floods the log at frame/detection rate.
"""

from __future__ import annotations


def should_log_throttled(count: int, every: int) -> bool:
    """True on the 1st occurrence and every ``every`` occurrences thereafter.

    ``every`` must be >= 1 (callers validate their config bound); with ``every == 1``
    this returns ``True`` on every call.
    """
    return count == 1 or count % every == 0
