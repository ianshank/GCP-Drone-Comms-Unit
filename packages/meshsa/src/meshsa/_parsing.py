"""Small, shared numeric parsers that fail with an *actionable* message.

Operator-facing inputs (env vars, CLI flags, config scalars) used to be parsed with
bare ``int(...)``/``float(...)``, so a typo surfaced as ``ValueError: invalid literal
for int() with base 10: 'xyz'`` with no hint about *which* setting was wrong. These
helpers name the offending field and (optionally) range-check it, so misconfiguration
is diagnosable from the message alone. They raise plain ``ValueError`` so existing
callers that already catch ``ValueError`` keep working — only the message improves.
"""

from __future__ import annotations


def parse_int(
    name: str, value: str | int | float, *, lo: int | None = None, hi: int | None = None
) -> int:
    """Parse ``value`` as an int named ``name``; optionally enforce ``lo <= n <= hi``."""
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name}: expected an integer, got {value!r}") from exc
    _check_range(name, parsed, lo, hi)
    return parsed


def parse_float(
    name: str, value: str | int | float, *, lo: float | None = None, hi: float | None = None
) -> float:
    """Parse ``value`` as a float named ``name``; optionally enforce ``lo <= x <= hi``."""
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name}: expected a number, got {value!r}") from exc
    _check_range(name, parsed, lo, hi)
    return parsed


def _check_range(name: str, parsed: float, lo: float | None, hi: float | None) -> None:
    if lo is not None and parsed < lo:
        raise ValueError(f"{name}: {parsed} is below the minimum {lo}")
    if hi is not None and parsed > hi:
        raise ValueError(f"{name}: {parsed} is above the maximum {hi}")
