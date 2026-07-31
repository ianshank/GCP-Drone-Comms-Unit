"""Direct tests for ``meshsa.netauth`` — the single audited bind/auth primitive.

Every guarded surface (llm server, commander, scout station, healthz) leans on this
module, but until now it was covered only *through* those callers. These tests pin the
primitives themselves — including the security-relevant edges (empty token, non-ASCII
token, scheme confusion) — so a behavior change here fails loudly and locally.
"""

from __future__ import annotations

import pytest
import structlog

from meshsa.netauth import (
    DEFAULT_POLICY,
    NetAuthPolicy,
    TransportAuthPolicy,
    authorize,
    is_loopback,
    validate_bind,
)


# ---- is_loopback -----------------------------------------------------------
@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost", "LOCALHOST", " 127.0.0.1 "])
def test_is_loopback_accepts_loopback_spellings(host):
    assert is_loopback(host)


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.5", "::", "example.com", ""])
def test_is_loopback_rejects_non_loopback(host):
    assert not is_loopback(host)


# ---- authorize -------------------------------------------------------------
def test_authorize_open_when_no_token_configured():
    # Loopback exposure is enforced separately by validate_bind; with no token set,
    # requests pass regardless of header.
    assert authorize(None, None)
    assert authorize("", "Bearer anything")


def test_authorize_requires_header_when_token_set():
    assert not authorize("s3cr3t", None)
    assert not authorize("s3cr3t", "")


def test_authorize_requires_bearer_scheme():
    assert not authorize("s3cr3t", "Basic s3cr3t")
    assert not authorize("s3cr3t", "s3cr3t")  # bare token, no scheme
    assert not authorize("s3cr3t", "Bearer")  # scheme with no credential


def test_authorize_rejects_wrong_token():
    assert not authorize("s3cr3t", "Bearer wrong")


def test_authorize_accepts_matching_token_case_insensitive_scheme():
    assert authorize("s3cr3t", "Bearer s3cr3t")
    assert authorize("s3cr3t", "bearer s3cr3t")
    assert authorize("s3cr3t", "Bearer  s3cr3t ")  # surrounding whitespace stripped


def test_authorize_non_ascii_token_compares_cleanly():
    # Comparison runs on UTF-8 bytes: a non-ASCII token must match itself and
    # cleanly reject a mismatch instead of raising TypeError.
    assert authorize("sécret", "Bearer sécret")
    assert not authorize("sécret", "Bearer secret")


# ---- validate_bind ---------------------------------------------------------
def test_validate_bind_loopback_needs_no_token():
    validate_bind("127.0.0.1", None, service="svc", remedy="unused")  # no raise


def test_validate_bind_non_loopback_without_token_fails_closed():
    with pytest.raises(ValueError, match="refusing to bind svc to '0.0.0.0'"):
        validate_bind("0.0.0.0", None, service="svc", remedy="set TOKEN")


def test_validate_bind_empty_token_is_no_token():
    # An empty credential must not satisfy the guard (the commander's historical
    # local copy used `token is None` and let "" through; the primitive must not).
    with pytest.raises(ValueError, match="without a token"):
        validate_bind("0.0.0.0", "", service="svc", remedy="set TOKEN")


def test_validate_bind_non_loopback_with_token_ok():
    validate_bind("0.0.0.0", "s3cr3t", service="svc", remedy="unused")  # no raise


def test_validate_bind_message_names_service_and_remedy():
    with pytest.raises(ValueError) as excinfo:
        validate_bind("10.0.0.1", None, service="the widget service", remedy="set WIDGET_TOKEN")
    message = str(excinfo.value)
    assert "the widget service" in message
    assert "set WIDGET_TOKEN" in message


# ---- validate_bind logging (every caller gets this for free) ---------------
def test_validate_bind_logs_warning_before_raising():
    # The refusal must be loud (a structured warning), not just the exception text that
    # only a crashing caller would surface — this is the real fail-closed path, not a mock.
    with (
        structlog.testing.capture_logs() as cap,
        pytest.raises(ValueError, match="refusing to bind"),
    ):
        validate_bind("0.0.0.0", None, service="svc", remedy="set TOKEN")
    [entry] = [e for e in cap if e["log_level"] == "warning"]
    assert entry["event"] == "refusing to bind without a token"
    assert entry["service"] == "svc"
    assert entry["host"] == "0.0.0.0"
    assert entry["remedy"] == "set TOKEN"


def test_validate_bind_does_not_log_when_the_bind_is_allowed():
    with structlog.testing.capture_logs() as cap:
        validate_bind("127.0.0.1", None, service="svc", remedy="unused")  # loopback, no token
        validate_bind("0.0.0.0", "s3cr3t", service="svc", remedy="unused")  # token present
    assert cap == []


# ---- TransportAuthPolicy seam ----------------------------------------------
def test_default_policy_is_a_transport_auth_policy():
    assert isinstance(DEFAULT_POLICY, TransportAuthPolicy)
    assert isinstance(NetAuthPolicy(), TransportAuthPolicy)


def test_net_auth_policy_delegates_validate_bind():
    policy = NetAuthPolicy()
    policy.validate_bind("127.0.0.1", None, service="svc", remedy="unused")  # no raise
    with pytest.raises(ValueError, match="refusing to bind"):
        policy.validate_bind("0.0.0.0", None, service="svc", remedy="set TOKEN")


def test_net_auth_policy_delegates_authorize():
    policy = NetAuthPolicy()
    assert policy.authorize(None, None)
    assert policy.authorize("s3cr3t", "Bearer s3cr3t")
    assert not policy.authorize("s3cr3t", "Bearer wrong")
