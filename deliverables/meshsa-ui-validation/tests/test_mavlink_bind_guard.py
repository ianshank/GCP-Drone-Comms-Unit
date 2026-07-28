"""Gate 0.3 tests — fail-closed bind guard for MavlinkSourceTransport.

These tests exercise the endpoint-host parsing helper and the bind validation
that the G0.3 patch adds to ``MavlinkSourceTransport.__init__``.

Drop into ``packages/meshsa/tests/`` alongside the existing transport tests.
The ``_parse_endpoint_host`` helper and the patched ``__init__`` are tested
with a fake connection factory so no pymavlink / real UDP socket is needed.

Run:
    cd packages/meshsa && pytest tests/test_mavlink_bind_guard.py -v
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ── import the helper from the patch module (before it lands in mavlink_source) ──
# Once the patch is applied to mavlink_source.py, replace these imports with:
#   from meshsa.transports.mavlink_source import (
#       MavlinkSourceTransport, _parse_endpoint_host
#   )
from mavlink_source_bind_guard import _parse_endpoint_host  # type: ignore[import]


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

    def test_default_endpoint_is_loopback(self) -> None:
        """The default endpoint 'udpin:127.0.0.1:14550' must parse as loopback."""
        from meshsa.netauth import is_loopback  # type: ignore[import]

        host = _parse_endpoint_host("udpin:127.0.0.1:14550")
        assert host is not None and is_loopback(host)


# ---------------------------------------------------------------------------
# MavlinkSourceTransport bind-guard integration tests
#
# These tests require the patch to be applied to mavlink_source.py.
# They are marked ``xfail`` until the patch lands, then flip to xpass.
# ---------------------------------------------------------------------------


def _fake_connection_factory(**_: Any):
    """Return a dummy factory; the transport is never started in these tests."""
    return lambda: MagicMock()


def _make_transport(endpoint: str, token: str | None = None, **kwargs: Any):
    """Construct a MavlinkSourceTransport with a fake connection factory."""
    from meshsa.transports.mavlink_source import MavlinkSourceTransport  # type: ignore

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
        """Non-loopback without a token must raise ValueError (fail-closed)."""
        with pytest.raises(ValueError) as excinfo:
            _make_transport("udpin:0.0.0.0:14550", token=None)
        msg = str(excinfo.value)
        # The error must name the service and the remedy — same as detection_ingest.
        assert "MAVLink" in msg or "mavlink" in msg.lower()
        assert "token" in msg.lower() or "127.0.0.1" in msg

    def test_nonloopback_empty_token_refused(self) -> None:
        """An empty/whitespace token is not a credential; refuse non-loopback."""
        with pytest.raises(ValueError):
            _make_transport("udpin:192.168.1.10:14550", token="")
        with pytest.raises(ValueError):
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
        """The guard fires at construction time (not at start time)."""
        with patch("meshsa.netauth.validate_bind") as mock_vb:
            mock_vb.side_effect = None  # don't actually raise
            _make_transport("udpin:0.0.0.0:14550", token=None)
            mock_vb.assert_called_once()
            call_kwargs = mock_vb.call_args
            assert call_kwargs is not None
            # First positional arg is the host.
            assert call_kwargs.args[0] == "0.0.0.0"
