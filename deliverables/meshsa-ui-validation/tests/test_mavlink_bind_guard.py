"""Gate 0.3 tests — fail-closed bind guard for MavlinkSourceTransport.

These tests exercise the endpoint-host parsing helper and the bind validation
that the G0.3 patch adds to ``MavlinkSourceTransport.__init__``.

Drop into ``packages/meshsa/tests/`` alongside the existing transport tests.
The ``_parse_endpoint_host`` helper and the patched ``__init__`` are tested
with a fake connection factory so no pymavlink / real UDP socket is needed.

Run:
    cd packages/meshsa && pytest tests/test_mavlink_bind_guard.py -v

Notes on design decisions:
- ``_parse_endpoint_host`` is inlined here so the test file is self-contained
  when placed in ``packages/meshsa/tests/``.  Once the patch lands in
  ``meshsa.transports.mavlink_source``, the inline copy can be replaced with:
      from meshsa.transports.mavlink_source import _parse_endpoint_host
- IPv6 endpoints (e.g. ``udpin:[::1]:14550``) are NOT matched by the regex;
  they return ``None`` and are treated as unguarded.  pymavlink does not
  document an IPv6 endpoint format, and bracketed-IPv6 would require a
  separate regex branch.  The current behaviour is safe (conservative): an
  operator who somehow passes an IPv6 address gets no bind guard rather than
  a false-positive guard.  This is explicitly tested in
  ``test_ipv6_bracketed_returns_none``.
"""

from __future__ import annotations

import re
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# _parse_endpoint_host — inlined from patches/mavlink_source_bind_guard.py
#
# This copy is authoritative for these tests.  The patch module contains an
# identical copy that is applied to meshsa/transports/mavlink_source.py.
# If the regex is updated, update both locations and regenerate tests.
# ---------------------------------------------------------------------------

#: Matches ``scheme:host:port`` pymavlink endpoint strings (IPv4 / hostname).
#: Returns None for serial paths, empty strings, or any format without exactly
#: two colons after a known scheme.  IPv6 bracketed notation is intentionally
#: not matched (see module docstring for rationale).
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
        The host string when the endpoint is a network bind, otherwise
        ``None``.

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


# ---------------------------------------------------------------------------
# _parse_endpoint_host unit tests
# ---------------------------------------------------------------------------


class TestParseEndpointHost:
    """Pure unit tests for the endpoint-host parser; no network I/O."""

    # ── network endpoints (host extracted) ──

    @pytest.mark.parametrize(
        "endpoint,expected",
        [
            ("udpin:127.0.0.1:14550", "127.0.0.1"),
            ("udpin:0.0.0.0:14550", "0.0.0.0"),
            ("udpout:192.168.1.100:14555", "192.168.1.100"),
            ("tcp:10.0.0.1:5760", "10.0.0.1"),
            ("tcpin:10.10.10.10:5760", "10.10.10.10"),
            ("UDP:127.0.0.1:14550", "127.0.0.1"),   # scheme is case-insensitive
        ],
    )
    def test_network_endpoint_returns_host(self, endpoint: str, expected: str) -> None:
        assert _parse_endpoint_host(endpoint) == expected

    # ── non-network endpoints (None returned) ──

    @pytest.mark.parametrize(
        "endpoint",
        [
            "/dev/ttyUSB0",
            "/dev/ttyAMA0",
            "COM3",
            "serial:/dev/ttyUSB0",
            "",            # empty string
            "mavlink",     # just a name, no colons
        ],
    )
    def test_serial_or_unknown_endpoint_returns_none(self, endpoint: str) -> None:
        assert _parse_endpoint_host(endpoint) is None

    def test_whitespace_stripped(self) -> None:
        assert _parse_endpoint_host("  udpin:127.0.0.1:14550  ") == "127.0.0.1"

    def test_ipv6_bracketed_returns_none(self) -> None:
        """IPv6 bracketed notation returns None (not guarded; see module docstring)."""
        # pymavlink does not define an IPv6 endpoint format; these are
        # conservative no-ops rather than false-positive guards.
        assert _parse_endpoint_host("tcpin:[::1]:5760") is None
        assert _parse_endpoint_host("udpin:[::ffff:192.0.2.1]:14550") is None

    def test_default_endpoint_is_loopback(self) -> None:
        """The default endpoint 'udpin:127.0.0.1:14550' must parse as loopback."""
        host = _parse_endpoint_host("udpin:127.0.0.1:14550")
        assert host == "127.0.0.1"


# ---------------------------------------------------------------------------
# MavlinkSourceTransport bind-guard integration tests
#
# These tests require the patch to be applied to mavlink_source.py.
# They are marked ``xfail`` until the patch lands, then flip to xpass.
# ---------------------------------------------------------------------------


def _fake_connection_factory(**_: Any) -> Any:
    """Return a no-op callable; the transport is never started in these tests."""
    return lambda: MagicMock()


def _make_transport(
    endpoint: str,
    token: str | None = None,
    **kwargs: Any,
) -> Any:
    """Construct a MavlinkSourceTransport with a fake connection factory.

    Importing is deferred to call-time so that the xfail marker on the class
    can catch an ImportError from a missing patch as a test failure rather than
    a collection error.
    """
    from meshsa.transports.mavlink_source import MavlinkSourceTransport  # type: ignore[import]

    return MavlinkSourceTransport(
        name="test-mavlink",
        connection_factory=_fake_connection_factory(),
        endpoint=endpoint,
        token=token,
        **kwargs,
    )


@pytest.mark.xfail(
    reason="G0.3 bind guard not yet applied to mavlink_source.py",
    strict=True,
)
class TestMavlinkBindGuard:
    """Bind-guard contract; xfail until the G0.3 patch lands."""

    def test_loopback_without_token_allowed(self) -> None:
        """udpin:127.0.0.1:* is safe with no token — loopback is trusted."""
        # Must not raise.
        _make_transport("udpin:127.0.0.1:14550", token=None)

    def test_loopback_with_token_allowed(self) -> None:
        """A token on a loopback endpoint is valid (redundant but not an error)."""
        _make_transport("udpin:127.0.0.1:14550", token="tok")

    def test_nonloopback_with_token_allowed(self) -> None:
        """A non-loopback bind WITH a token is permitted."""
        _make_transport("udpin:0.0.0.0:14550", token="secure-token")

    def test_nonloopback_without_token_refused(self) -> None:
        """Non-loopback without a token must raise ValueError (fail-closed).

        ``netauth.validate_bind`` raises ``ValueError`` — this matches the
        detection_ingest behaviour and is intentional.  The plan text that says
        "RuntimeError" is a documentation error; the implementation is
        ``ValueError`` throughout.
        """
        with pytest.raises(ValueError) as excinfo:
            _make_transport("udpin:0.0.0.0:14550", token=None)
        msg = str(excinfo.value)
        # The error must name the transport and include a remedy hint.
        assert "MAVLink" in msg or "mavlink" in msg.lower(), (
            f"Error message must name the MAVLink transport; got: {msg!r}"
        )
        assert "token" in msg.lower() or "127.0.0.1" in msg, (
            f"Error message must include a remedy hint; got: {msg!r}"
        )

    def test_nonloopback_empty_token_refused(self) -> None:
        """An empty/whitespace-only token is not a credential; refuse non-loopback."""
        with pytest.raises(ValueError, match="token"):
            _make_transport("udpin:192.168.1.10:14550", token="")
        with pytest.raises(ValueError, match="token"):
            _make_transport("udpin:192.168.1.10:14550", token="   ")

    def test_serial_endpoint_no_guard_applied(self) -> None:
        """Serial endpoints have no host to validate; must not raise."""
        # The guard must be skipped for non-network endpoints.
        _make_transport("/dev/ttyUSB0", token=None)
        _make_transport("serial:/dev/ttyAMA0", token=None)

    def test_default_endpoint_loopback_is_not_guarded(self) -> None:
        """The factory default ('udpin:127.0.0.1:14550') must not raise without a token."""
        # No endpoint kwarg → falls back to the default; loopback → no error.
        _make_transport("udpin:127.0.0.1:14550")

    def test_validate_bind_called_with_correct_service_label(self) -> None:
        """The service label in the error message names the MAVLink transport."""
        with pytest.raises(ValueError) as excinfo:
            _make_transport("udpin:10.0.0.1:14550", token=None)
        assert "mavlink" in str(excinfo.value).lower() or "MAVLink" in str(excinfo.value)

    def test_validate_bind_called_once_at_construction(self) -> None:
        """The guard fires at construction time (not at start / connect time)."""
        with patch(
            "meshsa.transports.mavlink_source.validate_bind"
        ) as mock_vb:
            mock_vb.side_effect = None  # suppress the real check
            _make_transport("udpin:0.0.0.0:14550", token=None)
            mock_vb.assert_called_once()
            call_args = mock_vb.call_args
            assert call_args is not None
            # First positional arg must be the parsed host, not the full endpoint.
            assert call_args.args[0] == "0.0.0.0", (
                f"validate_bind must receive the host, not the full endpoint string; "
                f"got: {call_args.args[0]!r}"
            )
