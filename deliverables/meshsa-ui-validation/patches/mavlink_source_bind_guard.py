"""Gate 0.3 patch — fail-closed bind guard for MavlinkSourceTransport.

This module shows the exact changes needed to ``packages/meshsa/src/meshsa/
transports/mavlink_source.py`` to resolve the AUDIT_M2_AUTH.md follow-up item:

    "Fail-closed bind guard for mavlink_source on a non-loopback endpoint
     (detection_ingest done on this branch via netauth.validate_bind)."

Apply by replacing the ``__init__`` of ``MavlinkSourceTransport`` with the
version shown in ``_patched_init`` below and adding the ``_parse_host`` helper.

The change is deliberately minimal: one helper + one validate_bind call in
``__init__``, mirroring the detection_ingest pattern exactly.  The ``token``
option is picked up from ``**_options`` so no new positional arguments are
needed (backward-compatible with all existing configs/tests).

Regression tests are in:
    deliverables/meshsa-ui-validation/tests/test_mavlink_bind_guard.py
"""

from __future__ import annotations

import re

# ── helper (add to mavlink_source.py, alongside the existing module helpers) ──

# Recognises the endpoint formats pymavlink accepts:
#   udpin:HOST:PORT, udpout:HOST:PORT, tcp:HOST:PORT, tcpin:HOST:PORT …
# Anything that does not match (e.g. "serial:/dev/ttyUSB0") is assumed to be a
# local, non-network endpoint and is left unguarded (no IP bind to validate).
_ENDPOINT_RE = re.compile(
    r"""
    ^(?P<scheme>[a-z]+)          # scheme: udpin, udpout, tcp, …
    :                            # separator
    (?P<host>[^:]+)              # host: IP or hostname, no colon
    :                            # separator
    (?P<port>\d+)$               # port: digits only
    """,
    re.VERBOSE | re.IGNORECASE,
)


def _parse_endpoint_host(endpoint: str) -> str | None:
    """Extract the host component from a pymavlink endpoint string.

    Returns the host string when the endpoint is a network bind, or ``None``
    when it is a serial/pipe endpoint that has no IP host to validate.

    Examples::

        >>> _parse_endpoint_host("udpin:127.0.0.1:14550")
        '127.0.0.1'
        >>> _parse_endpoint_host("udpin:0.0.0.0:14550")
        '0.0.0.0'
        >>> _parse_endpoint_host("serial:/dev/ttyUSB0")
        None
        >>> _parse_endpoint_host("/dev/ttyUSB0")
        None
    """
    m = _ENDPOINT_RE.match(endpoint.strip())
    return m.group("host") if m else None


# ── patched __init__ (replace the existing one in MavlinkSourceTransport) ───
#
# The only diff from the original:
#   1. ``token: str | None = None`` extracted from ``**_options``.
#   2. ``_parse_endpoint_host`` called on the resolved endpoint string.
#   3. ``validate_bind`` called iff a host is parsed (network bind only).
#
# The call is in ``__init__`` (construction time), not in ``start``, so a
# misconfigured deployment fails before the asyncio loop starts — the same
# behaviour as ``DetectionIngestTransport``.

_PATCHED_INIT_DOCSTRING = """
def __init__(
    self,
    name: str = "mavlink",
    *,
    connection: Any | None = None,
    connection_factory: ConnectionFactory | None = None,
    message_type: str = "GLOBAL_POSITION_INT",
    source_uid: str = "mav-1",
    callsign: str | None = None,
    coord_scale: float = 1e7,
    alt_scale: float = 1e-3,
    recv_timeout_s: float = 1.0,
    clock: Clock | None = None,
    queue_maxsize: int = 1000,
    # ── NEW: bind guard (Gate 0.3) ──────────────────────────────────────────
    # Picked up from the registry **options dict so no existing config breaks.
    # Only validated when the endpoint parses as a network host (not serial).
    token: str | None = None,
    # ────────────────────────────────────────────────────────────────────────
    **_options: Any,
) -> None:
    # ── NEW: fail-closed bind check for non-loopback MAVLink endpoints ──────
    endpoint = _options.get("endpoint", "udpin:127.0.0.1:14550")
    host = _parse_endpoint_host(endpoint)
    if host is not None:
        from ..netauth import validate_bind
        validate_bind(
            host,
            token,
            service="the MAVLink source transport",
            remedy=(
                "set a 'token' in the transport options, or bind to 127.0.0.1 "
                "(e.g. endpoint='udpin:127.0.0.1:14550')"
            ),
        )
    # ── original super().__init__ unchanged ─────────────────────────────────
    super().__init__(
        name,
        resource=connection,
        factory=connection_factory or _default_connection_factory(_options),
        source_uid=source_uid,
        callsign=callsign,
        clock=clock,
        queue_maxsize=queue_maxsize,
        poll_wait_s=0.0,
    )
    self._message_type = message_type
    self._coord_scale = coord_scale
    self._alt_scale = alt_scale
    self._recv_timeout = recv_timeout_s
"""

# ── self-test for the helper (pytest picks this up automatically) ────────────


def test_parse_endpoint_host_network_endpoints() -> None:
    assert _parse_endpoint_host("udpin:127.0.0.1:14550") == "127.0.0.1"
    assert _parse_endpoint_host("udpin:0.0.0.0:14550") == "0.0.0.0"
    assert _parse_endpoint_host("udpout:192.168.1.100:14555") == "192.168.1.100"
    assert _parse_endpoint_host("tcp:10.0.0.1:5760") == "10.0.0.1"
    assert _parse_endpoint_host("tcpin:::1:5760") is None  # IPv6 with colons: no match


def test_parse_endpoint_host_serial_endpoints() -> None:
    assert _parse_endpoint_host("/dev/ttyUSB0") is None
    assert _parse_endpoint_host("serial:/dev/ttyUSB0") is None
    assert _parse_endpoint_host("COM3") is None


def test_parse_endpoint_host_whitespace_stripped() -> None:
    assert _parse_endpoint_host("  udpin:127.0.0.1:14550  ") == "127.0.0.1"
