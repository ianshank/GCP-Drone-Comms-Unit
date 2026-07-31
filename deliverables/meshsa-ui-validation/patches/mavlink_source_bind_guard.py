"""Gate 0.3 patch — fail-closed bind guard for MavlinkSourceTransport.

This module shows the exact changes needed to ``packages/meshsa/src/meshsa/
transports/mavlink_source.py`` to resolve the follow-up backlog item from
``docs/AUDIT_M2_AUTH.md``:

    "Fail-closed bind guard for mavlink_source on a non-loopback endpoint
     (detection_ingest done on this branch via netauth.validate_bind)."

How to apply
------------
1. Copy ``_ENDPOINT_RE`` and ``_parse_endpoint_host`` into
   ``mavlink_source.py`` at module level (after the existing imports).
2. Add ``validate_bind`` to the imports at the top of ``mavlink_source.py``::

       from ..netauth import validate_bind

3. In ``MavlinkSourceTransport.__init__``, add the guard block shown in
   ``_GUARD_BLOCK`` (after ``**_options`` is available, before
   ``super().__init__``).
4. Add ``token: str | None = None`` to the ``__init__`` keyword arguments
   (extracted from ``**_options`` via the guard block — no positional-arg
   change needed; backward-compatible with all existing configs and tests).

Design rationale
----------------
* The guard is at ``__init__`` (construction time), not ``start`` time —
  a misconfigured deployment fails before the asyncio loop starts, identical
  to ``DetectionIngestTransport``.
* The import of ``validate_bind`` is at module level (not lazy inside
  ``__init__``) to make the dependency explicit and allow static type
  checkers to resolve it.  The ``netauth`` module has no circular-import
  risk with ``mavlink_source``.
* IPv6 endpoints are intentionally not matched by ``_ENDPOINT_RE``; they
  return ``None`` from ``_parse_endpoint_host`` and are left unguarded.
  pymavlink does not document an IPv6 endpoint format; bracketed-IPv6 would
  require a separate regex branch and a separate test matrix.  The behaviour
  is conservative (no false-positive guard) rather than failing closed on an
  unseen format.

Regression tests
----------------
``deliverables/meshsa-ui-validation/tests/test_mavlink_bind_guard.py``
(drop into ``packages/meshsa/tests/`` alongside existing transport tests).
"""

from __future__ import annotations

import re

# ── 1. Module-level regex (add after existing imports in mavlink_source.py) ──

#: Matches pymavlink network endpoint strings of the form ``scheme:host:port``.
#: Scheme is case-insensitive (``udpin``, ``UDPIN``, ``tcp``, …).
#: Host is any sequence of non-colon characters (IPv4 dotted-decimal or
#: hostname).  IPv6 bracketed notation (``[::1]``) is not matched; those
#: endpoints return ``None`` and are left unguarded (see module docstring).
_ENDPOINT_RE = re.compile(
    r"""
    ^(?P<scheme>[a-z]+)          # scheme: udpin, udpout, tcp, tcpin …
    :                            # first separator
    (?P<host>[^:]+)              # host: any chars except colon (IPv4 or hostname)
    :                            # second separator
    (?P<port>\d+)$               # port: digits only, anchored at end
    """,
    re.VERBOSE | re.IGNORECASE,
)


# ── 2. Helper function (add after _ENDPOINT_RE) ───────────────────────────────


def _parse_endpoint_host(endpoint: str) -> str | None:
    """Extract the host component from a pymavlink network endpoint string.

    Returns the host string for network endpoints (``udpin:``, ``udpout:``,
    ``tcp:``, ``tcpin:`` …), or ``None`` for serial/pipe endpoints and any
    string that does not match the ``scheme:host:port`` pattern.

    Args:
        endpoint: A pymavlink connection string such as
            ``"udpin:127.0.0.1:14550"`` or a serial path like
            ``"/dev/ttyUSB0"``.

    Returns:
        The host string when the endpoint is a parseable network bind,
        otherwise ``None``.

    Examples::

        >>> _parse_endpoint_host("udpin:127.0.0.1:14550")
        '127.0.0.1'
        >>> _parse_endpoint_host("udpin:0.0.0.0:14550")
        '0.0.0.0'
        >>> _parse_endpoint_host("serial:/dev/ttyUSB0")
        None
        >>> _parse_endpoint_host("/dev/ttyUSB0")
        None
        >>> _parse_endpoint_host("  udpin:192.168.1.10:14550  ")
        '192.168.1.10'
    """
    m = _ENDPOINT_RE.match(endpoint.strip())
    return m.group("host") if m else None


# ── 3. Import addition for mavlink_source.py (top of file, with other imports) ─
#
# Add alongside the existing netauth import if present, or add a new import:
#
#   from ..netauth import validate_bind
#
# This is a module-level import (not lazy) to keep the dependency explicit.


# ── 4. Guard block to add inside MavlinkSourceTransport.__init__ ─────────────
#
# Add as the FIRST thing inside __init__, before super().__init__().
# ``token`` is sourced from ``**_options`` (backward-compatible; callers that
# don't pass ``token`` get ``None`` and are only guarded on non-loopback).
#
# Paste this block verbatim into the __init__ body:

_GUARD_BLOCK = """
    # ── Gate 0.3: fail-closed bind guard ────────────────────────────────────
    # Non-loopback MAVLink endpoints require a token (mirrors detection_ingest).
    # Construction-time check so misconfigured deployments fail before the
    # asyncio loop starts.
    _endpoint_str: str = _options.get("endpoint", "udpin:127.0.0.1:14550")
    _bind_host = _parse_endpoint_host(_endpoint_str)
    if _bind_host is not None:
        validate_bind(
            _bind_host,
            token,
            service="the MAVLink source transport",
            remedy=(
                "set a 'token' in the transport options, or use a loopback "
                "endpoint (e.g. endpoint='udpin:127.0.0.1:14550')"
            ),
        )
    # ── end Gate 0.3 guard ──────────────────────────────────────────────────
"""

# ── 5. Updated __init__ signature (add ``token`` as keyword-only arg) ────────
#
# Before the ``**_options`` parameter, add:
#   token: str | None = None,
#
# This is the only signature change.  All existing callers that do not pass
# ``token`` are unaffected (default is ``None``).


# ── Self-tests (pytest picks these up; run with: pytest patches/ -v) ─────────


def test_parse_endpoint_host_network_endpoints() -> None:
    """Standard network endpoint strings return the host component."""
    cases = [
        ("udpin:127.0.0.1:14550", "127.0.0.1"),
        ("udpin:0.0.0.0:14550", "0.0.0.0"),
        ("udpout:192.168.1.100:14555", "192.168.1.100"),
        ("tcp:10.0.0.1:5760", "10.0.0.1"),
        ("tcpin:10.10.10.10:5760", "10.10.10.10"),
        ("UDP:127.0.0.1:14550", "127.0.0.1"),  # case-insensitive scheme
        ("  udpin:192.168.1.10:14550  ", "192.168.1.10"),  # leading/trailing ws
    ]
    for endpoint, expected in cases:
        result = _parse_endpoint_host(endpoint)
        assert result == expected, (
            f"_parse_endpoint_host({endpoint!r}) = {result!r}; expected {expected!r}"
        )


def test_parse_endpoint_host_serial_and_unknown() -> None:
    """Serial paths, plain device names, and empty strings return None."""
    for endpoint in ["/dev/ttyUSB0", "serial:/dev/ttyUSB0", "COM3", "", "mavlink"]:
        assert _parse_endpoint_host(endpoint) is None, (
            f"_parse_endpoint_host({endpoint!r}) should be None"
        )


def test_parse_endpoint_host_ipv6_returns_none() -> None:
    """IPv6 bracketed notation returns None (conservative: unguarded, not error)."""
    for endpoint in ["tcpin:[::1]:5760", "udpin:[::ffff:192.0.2.1]:14550"]:
        assert _parse_endpoint_host(endpoint) is None, (
            f"IPv6 endpoint {endpoint!r} should return None "
            "(not matched; see module docstring for rationale)"
        )
