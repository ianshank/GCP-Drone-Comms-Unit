"""Shared HTTP bind/auth primitives for the repo's small aiohttp services.

Loopback detection, constant-time bearer authorisation, and fail-closed bind validation are
security-sensitive and were previously copied per service (``meshsa.llm.server`` and the scout
station). Centralising them here keeps a single audited implementation (CHARTER §4: reuse, do
not fork the proven primitives) that both services re-export.
"""

from __future__ import annotations

import hmac

#: Hosts treated as loopback-only (safe to serve without a bearer token).
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def is_loopback(host: str) -> bool:
    """True when ``host`` is a loopback bind that needs no network auth."""
    return host.strip().lower() in _LOOPBACK_HOSTS


def authorize(token: str | None, auth_header: str | None) -> bool:
    """Whether a request may proceed (pure; no web framework).

    Open when no token is configured (loopback is enforced separately by
    :func:`validate_bind`). When a token is set, require a constant-time-matching
    ``Authorization: Bearer <token>`` header. The comparison runs on UTF-8 bytes so a
    non-ASCII token/header yields a clean ``False`` instead of a ``TypeError``.
    """
    if not token:
        return True
    if not auth_header:
        return False
    scheme, _, presented = auth_header.partition(" ")
    if scheme.lower() != "bearer" or not presented:
        return False
    return hmac.compare_digest(presented.strip().encode("utf-8"), token.encode("utf-8"))


def validate_bind(host: str, token: str | None, *, service: str, remedy: str) -> None:
    """Fail closed: a non-loopback bind without a token is a misconfiguration.

    Raises :class:`ValueError` so an entry point can refuse to start rather than silently
    exposing an unauthenticated service. ``service`` names the binary and ``remedy`` explains
    what to set, so each caller keeps its own operator-facing message.
    """
    if not is_loopback(host) and not token:
        raise ValueError(f"refusing to bind {service} to {host!r} without a token: {remedy}")
