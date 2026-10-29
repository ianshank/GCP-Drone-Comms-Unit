"""Unit tests for ``meshsa._web`` — the shared aiohttp kit's pure parts (design D-5).

The four app factories exercise the kit end to end (``test_app_contracts.py``); these pin
the helpers directly so a regression names the primitive, not a route.
"""

from __future__ import annotations

from typing import Any

import pytest
import structlog

from meshsa._web import (
    NO_STORE_HEADERS,
    UNAUTHORIZED_BODY,
    ServiceAuth,
    normalize_token,
    read_json_or_none,
    register_routes,
    text_body,
    unauthorized,
    upstream_error,
)
from meshsa.netauth import validate_bind


@pytest.mark.parametrize(
    "raw, expected",
    [(None, None), ("", None), ("   ", None), ("\n\t", None), (" tok ", "tok"), ("tok", "tok")],
)
def test_normalize_token(raw: str | None, expected: str | None) -> None:
    assert normalize_token(raw) == expected


def test_service_auth_keeps_the_token_verbatim_and_challenges() -> None:
    auth = ServiceAuth("meshsa-x", "tok")
    assert auth.token == "tok"
    assert auth.challenge == 'Bearer realm="meshsa-x"'
    assert auth.allows("Bearer tok")
    assert auth.allows("bearer tok")  # scheme is case-insensitive, like netauth.authorize
    assert not auth.allows("Bearer nope")
    assert not auth.allows(None)
    assert auth.allows_query_token("tok")
    assert not auth.allows_query_token("nope")
    assert not auth.allows_query_token(None)
    # No normalisation inside the kit: a padded token is carried as configured, and since
    # authorize strips only the *presented* credential it is unmatchable — locked, not open.
    padded = ServiceAuth("meshsa-x", "  tok \n")
    assert padded.token == "  tok \n"
    assert not padded.allows("Bearer tok")
    assert not padded.allows("Bearer   tok \n")


def test_service_auth_open_only_when_token_is_none_or_empty() -> None:
    for raw in (None, ""):
        auth = ServiceAuth("meshsa-x", raw)
        assert auth.allows(None)
        assert auth.allows_query_token(None)
    # Regression (Phase 2a security review): a whitespace-only token passes
    # netauth.validate_bind (`not "   "` is False), so the kit must NOT treat it as open —
    # that would turn a locked non-loopback surface into an unauthenticated one.
    for raw in ("   ", "\n\t"):
        auth = ServiceAuth("meshsa-x", raw)
        assert not auth.allows(None)
        assert not auth.allows("Bearer " + raw)
        assert not auth.allows_query_token(raw)


@pytest.mark.parametrize("raw", [None, "", "   ", "\n\t", "tok", "  tok "])
def test_service_auth_is_open_iff_the_bind_check_would_refuse(raw: str | None) -> None:
    """The invariant behind the fix: open-to-all ⇔ validate_bind refuses a non-loopback bind."""
    try:
        validate_bind("0.0.0.0", raw, service="svc", remedy="r")
        bind_refused = False
    except ValueError:
        bind_refused = True
    assert ServiceAuth("svc", raw).allows(None) is bind_refused


def test_service_auth_is_frozen() -> None:
    auth = ServiceAuth("meshsa-x", "tok")
    with pytest.raises(AttributeError):
        auth.token = "other"  # type: ignore[misc]


def test_unauthorized_response_shape() -> None:
    pytest.importorskip("aiohttp")
    resp = unauthorized(ServiceAuth("meshsa-x", "tok"))
    assert resp.status == 401
    assert resp.headers["Cache-Control"] == "no-store"
    assert resp.headers["WWW-Authenticate"] == 'Bearer realm="meshsa-x"'
    assert resp.text == '{"error": "unauthorized"}'
    assert UNAUTHORIZED_BODY == {"error": "unauthorized"}
    assert NO_STORE_HEADERS == {"Cache-Control": "no-store"}


def test_text_body_is_no_store_with_status() -> None:
    pytest.importorskip("aiohttp")
    resp = text_body("a,b\n", content_type="text/csv", status=201)
    assert resp.status == 201
    assert resp.headers["Cache-Control"] == "no-store"
    assert resp.content_type == "text/csv"


class _Request:
    def __init__(self, *, body: Any = None, raises: Exception | None = None) -> None:
        self._body = body
        self._raises = raises

    async def json(self) -> Any:
        if self._raises is not None:
            raise self._raises
        return self._body


async def test_read_json_or_none_returns_body_or_none() -> None:
    assert await read_json_or_none(_Request(body={"a": 1})) == {"a": 1}
    assert await read_json_or_none(_Request(raises=ValueError("bad"))) is None


async def test_read_json_or_none_logs_only_when_asked() -> None:
    log = structlog.get_logger("test")
    with structlog.testing.capture_logs() as cap:
        await read_json_or_none(_Request(raises=ValueError("bad")))
    assert cap == []
    with structlog.testing.capture_logs() as cap:
        await read_json_or_none(
            _Request(raises=ValueError("bad")), log=log, route="/r", event="parse_failed"
        )
    [entry] = cap
    assert entry["event"] == "parse_failed"
    assert entry["route"] == "/r"
    assert entry["error"] == "bad"
    assert entry["error_type"] == "ValueError"


def test_upstream_error_is_generic_and_logged() -> None:
    pytest.importorskip("aiohttp")
    log = structlog.get_logger("test")
    with structlog.testing.capture_logs() as cap:
        resp = upstream_error(
            log, "/api/x", RuntimeError("sqlite:///secret"), message="generic", event="boom"
        )
    assert resp.status == 502
    assert resp.headers["Cache-Control"] == "no-store"
    assert "secret" not in resp.text
    [entry] = cap
    assert entry["event"] == "boom"
    assert entry["route"] == "/api/x"
    assert entry["error"] == "sqlite:///secret"
    assert entry["error_type"] == "RuntimeError"


def test_register_routes_wires_the_table_in_order() -> None:
    pytest.importorskip("aiohttp")
    from aiohttp import web

    async def a(_request: Any) -> Any:
        return web.Response()

    app = web.Application()
    register_routes(app, [("GET", "/a", a), ("POST", "/b", a)])
    inventory = {
        (route.method, route.resource.canonical)
        for route in app.router.routes()
        if route.method != "HEAD"
    }
    assert inventory == {("GET", "/a"), ("POST", "/b")}
