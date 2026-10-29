"""Fail-closed aiohttp app factory for the operator console (spec §5.3, design D-2/D-7).

Pure helpers (``validate_bind``/``guard``/``panel_manifest``) are unit-tested without a web
framework; ``build_ui_app`` wires them into routes. The read-only contract (I-2): every
route is GET except ``POST /api/chat``, which answers questions and mutates nothing —
asserted mechanically by the route-table test.

Auth (the audited station pattern, via :mod:`meshsa._web`): when a token is configured,
``/api/*`` requires ``Authorization: Bearer <token>``; ``/`` is gated by a ``?token=`` query
(browsers cannot set headers on navigation) and served with the token JSON-injected for its
fetches; ``/healthz`` stays open (liveness; discloses nothing — house norm). A raising source
yields a **generic** 502 with the detail logged server-side only (the llm policy),
per-path — no blanket catch.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import structlog

from .._web import (
    UNAUTHORIZED_BODY,
    Handler,
    ServiceAuth,
    api_json,
    guarded,
    healthz,
    html_page,
    normalize_token,
    page_token_gate,
    read_json_or_none,
    register_routes,
    upstream_error,
)

# Re-exported for callers/tests; the explicit ``as`` alias satisfies no_implicit_reexport.
from ..netauth import authorize as authorize
from ..netauth import is_loopback as is_loopback
from ..netauth import validate_bind as _validate_bind
from ._html import render_page
from .config import UIConfig
from .sources import ChatBackend, UISources

_log = structlog.get_logger("meshsa.ui.app")

__all__ = [
    "authorize",
    "is_loopback",
    "validate_bind",
    "guard",
    "panel_manifest",
    "build_ui_app",
    "UPSTREAM_ERROR",
]

#: Stable, non-sensitive body returned to the browser when a data source raises.
UPSTREAM_ERROR = "source unavailable; check the server logs"


def validate_bind(host: str, token: str | None) -> None:
    """Fail closed: a non-loopback console bind without a token is a misconfiguration."""
    _validate_bind(
        host,
        token,
        service="meshsa-ui",
        remedy=(
            "the console shows live positions, health, and logs. Set MESHSA_UI_TOKEN "
            "to a strong secret, or bind to 127.0.0.1."
        ),
    )


def guard(token: str | None, auth_header: str | None) -> tuple[dict[str, Any], int] | None:
    """Bearer check for the data routes (pure): ``None`` = allowed, else ``(body, 401)``."""
    if authorize(token, auth_header):
        return None
    return dict(UNAUTHORIZED_BODY), 401


def panel_manifest(sources: UISources) -> list[str]:
    """Panels the page should render (pure): optional panels appear iff wired (D-7).

    Construction-time gating is the wiring's job (``meshsa.ui.cli.build_sources`` only
    creates a source when its config flag is on); here, presence is truth.
    """
    manifest = ["tracks", "detections", "health"]
    if sources.fpv is not None:
        manifest.append("fpv")
    if sources.chat is not None:
        manifest.append("chat")
    if sources.logs is not None:
        manifest.append("logs")
    return manifest


def _json_route(auth: ServiceAuth, route: str, read: Callable[[], Any]) -> Handler:
    """A bearer-guarded GET that serves ``read()`` as JSON, or the generic 502 if it raises."""

    async def handler(_request: Any) -> Any:
        try:
            return api_json(read())
        except Exception as exc:
            return upstream_error(_log, route, exc, message=UPSTREAM_ERROR, event="ui_source_error")

    return guarded(auth, handler)


def _chat_route(auth: ServiceAuth, backend: ChatBackend) -> Handler:
    """``POST /api/chat``: the one non-GET route; it answers questions and mutates nothing."""

    async def handler(request: Any) -> Any:
        payload = await read_json_or_none(
            request, log=_log, route="/api/chat", event="ui_chat_payload_parse_error"
        )
        try:
            body, status = await backend.reply(payload)
        except Exception as exc:  # a raising backend still yields the generic 502
            return upstream_error(
                _log, "/api/chat", exc, message=UPSTREAM_ERROR, event="ui_source_error"
            )
        return api_json(body, status=status)

    return guarded(auth, handler)


def build_ui_app(
    sources: UISources,
    config: UIConfig,
    *,
    host: str | None = None,
    token: str | None = None,
) -> Any:
    """Build the console aiohttp app.

    When ``host`` is given, the fail-closed bind rule is enforced **inside** the factory
    (the scout pattern: the guarantee travels with the app, so embedders inherit it).
    ``token`` overrides ``config.token`` when set; both empty/whitespace forms mean "no
    token" (``UIConfig`` normalises at load, and the override is normalised here the same
    way — a whitespace credential must not satisfy the fail-closed bind check). Routes for
    absent optional sources are not registered at all — 404 by absence, not an error state.
    """
    effective_token = normalize_token(token) if token is not None else config.token
    if host is not None:
        validate_bind(host, effective_token)
    from aiohttp import web

    auth = ServiceAuth("meshsa-ui", effective_token)
    manifest = panel_manifest(sources)

    async def index(request: Any) -> Any:
        denied = page_token_gate(auth, request)
        if denied is not None:
            return denied
        page = render_page(
            effective_token,
            manifest,
            poll_interval_s=config.poll_interval_s,
            map_style_url=config.map_style_url,
            title=config.title,
        )
        # The page embeds the bearer token and is reached via ``?token=``: keep it out of
        # the browser's disk cache (history retention is inherent to the station pattern).
        return html_page(page)

    def health_body() -> dict[str, Any]:
        body: dict[str, Any] = {"snapshot": sources.snapshot.counters()}
        if sources.health is not None:
            body.update(sources.health.snapshot())
        return body

    routes: list[tuple[str, str, Handler]] = [
        ("GET", "/", index),
        ("GET", "/healthz", healthz),
        ("GET", "/api/tracks", _json_route(auth, "/api/tracks", sources.snapshot.tracks_geojson)),
        (
            "GET",
            "/api/detections",
            _json_route(auth, "/api/detections", sources.snapshot.detections_geojson),
        ),
        ("GET", "/api/health", _json_route(auth, "/api/health", health_body)),
    ]
    if sources.fpv is not None:
        routes.append(("GET", "/api/fpv", _json_route(auth, "/api/fpv", sources.fpv.report)))
    if sources.chat is not None:
        routes.append(("POST", "/api/chat", _chat_route(auth, sources.chat)))
    if sources.logs is not None:
        log_source = sources.logs
        routes.append(
            (
                "GET",
                "/api/logs",
                _json_route(auth, "/api/logs", lambda: {"entries": log_source.entries()}),
            )
        )

    app = web.Application()
    register_routes(app, routes)
    return app
