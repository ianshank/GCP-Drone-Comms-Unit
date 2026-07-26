"""Fail-closed aiohttp app factory for the operator console (spec §5.3, design D-2/D-7).

Pure helpers (``validate_bind``/``guard``/``panel_manifest``) are unit-tested without a web
framework; ``build_ui_app`` wires them into routes. The read-only contract (I-2): every
route is GET except ``POST /api/chat``, which answers questions and mutates nothing —
asserted mechanically by the route-table test.

Auth (the audited station pattern): when a token is configured, ``/api/*`` requires
``Authorization: Bearer <token>``; ``/`` is gated by a ``?token=`` query (browsers cannot
set headers on navigation) and served with the token JSON-injected for its fetches;
``/healthz`` stays open (liveness; discloses nothing — house norm). A raising source
yields a **generic** 502 with the detail logged server-side only (the llm policy),
per-path — no blanket catch.
"""

from __future__ import annotations

from typing import Any

import structlog

# Re-exported for callers/tests; the explicit ``as`` alias satisfies no_implicit_reexport.
from ..netauth import authorize as authorize
from ..netauth import is_loopback as is_loopback
from ..netauth import validate_bind as _validate_bind
from ._html import render_page
from .config import UIConfig
from .sources import UISources

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
    return {"error": "unauthorized"}, 401


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
    token" (``UIConfig`` normalises at load). Routes for absent optional sources are not
    registered at all — 404 by absence, not an error state.
    """
    effective_token = token if token is not None else config.token
    if host is not None:
        validate_bind(host, effective_token)
    from aiohttp import web

    manifest = panel_manifest(sources)

    def _denied(request: Any) -> Any | None:
        result = guard(effective_token, request.headers.get("Authorization"))
        if result is None:
            return None
        body, status = result
        return web.json_response(body, status=status)

    def _upstream_error(route: str, exc: Exception) -> Any:
        # Generic body to the browser; the detail is logged server-side only (llm policy).
        _log.warning("ui_source_error", route=route, error=str(exc), error_type=type(exc).__name__)
        return web.json_response({"error": UPSTREAM_ERROR}, status=502)

    async def index(request: Any) -> Any:
        # Browsers can't set an Authorization header on navigation: gate the page on a
        # ``?token=`` query, then inject the token for its fetch calls (station pattern).
        if effective_token and not authorize(
            effective_token, "Bearer " + (request.query.get("token") or "")
        ):
            return web.json_response({"error": "unauthorized"}, status=401)
        page = render_page(
            effective_token,
            manifest,
            poll_interval_s=config.poll_interval_s,
            map_style_url=config.map_style_url,
            title=config.title,
        )
        return web.Response(text=page, content_type="text/html")

    async def healthz(_request: Any) -> Any:
        return web.json_response({"status": "ok"})

    async def tracks(request: Any) -> Any:
        denied = _denied(request)
        if denied is not None:
            return denied
        try:
            return web.json_response(sources.snapshot.tracks_geojson())
        except Exception as exc:
            return _upstream_error("/api/tracks", exc)

    async def detections(request: Any) -> Any:
        denied = _denied(request)
        if denied is not None:
            return denied
        try:
            return web.json_response(sources.snapshot.detections_geojson())
        except Exception as exc:
            return _upstream_error("/api/detections", exc)

    async def health(request: Any) -> Any:
        denied = _denied(request)
        if denied is not None:
            return denied
        try:
            body: dict[str, Any] = {"snapshot": sources.snapshot.counters()}
            if sources.health is not None:
                body.update(sources.health.snapshot())
            return web.json_response(body)
        except Exception as exc:
            return _upstream_error("/api/health", exc)

    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/healthz", healthz)
    app.router.add_get("/api/tracks", tracks)
    app.router.add_get("/api/detections", detections)
    app.router.add_get("/api/health", health)

    if sources.fpv is not None:
        fpv_source = sources.fpv

        async def fpv(request: Any) -> Any:
            denied = _denied(request)
            if denied is not None:
                return denied
            try:
                return web.json_response(fpv_source.report())
            except Exception as exc:
                return _upstream_error("/api/fpv", exc)

        app.router.add_get("/api/fpv", fpv)

    if sources.chat is not None:
        chat_backend = sources.chat

        async def chat(request: Any) -> Any:
            denied = _denied(request)
            if denied is not None:
                return denied
            try:
                payload = await request.json()
            except Exception:
                payload = None
            try:
                body, status = await chat_backend.reply(payload)
            except Exception as exc:  # a raising backend still yields the generic 502
                return _upstream_error("/api/chat", exc)
            return web.json_response(body, status=status)

        app.router.add_post("/api/chat", chat)

    if sources.logs is not None:
        log_source = sources.logs

        async def logs(request: Any) -> Any:
            denied = _denied(request)
            if denied is not None:
                return denied
            try:
                return web.json_response({"entries": log_source.entries()})
            except Exception as exc:
                return _upstream_error("/api/logs", exc)

        app.router.add_get("/api/logs", logs)

    return app
