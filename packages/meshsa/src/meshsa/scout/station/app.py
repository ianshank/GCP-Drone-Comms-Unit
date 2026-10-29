"""aiohttp station: serve pins, triage, and exports over a fail-closed app.

Pure helpers (``authorize``/``is_loopback``/``validate_bind``/``detections_geojson``/
``set_status_body``) are unit-tested without a web framework; ``build_app`` wires them into
aiohttp routes through the shared :mod:`meshsa._web` kit. Data + mutation endpoints require
``Authorization: Bearer <token>`` when a token is set; a non-loopback bind without a token is
refused (fail-closed), mirroring ``meshsa.llm.server``.
"""

from __future__ import annotations

from typing import Any

import structlog

from ..._web import (
    Handler,
    ServiceAuth,
    api_json,
    guarded,
    healthz,
    html_page,
    page_token_gate,
    read_json_or_none,
    register_routes,
    text_body,
)
from ...netauth import authorize, is_loopback
from ...netauth import validate_bind as _validate_bind
from ..protocols import Store
from ..schemas import DETECTION_STATUSES
from ..store import to_csv, to_geojson
from ._html import render_page

_log = structlog.get_logger("meshsa.scout.station")

__all__ = [
    "authorize",
    "is_loopback",
    "validate_bind",
    "detections_geojson",
    "set_status_body",
    "build_app",
]


def validate_bind(host: str, token: str | None) -> None:
    """Fail closed: a non-loopback bind without a token is a misconfiguration."""
    _validate_bind(
        host,
        token,
        service="meshsa-scout station",
        remedy=(
            "the station discloses detection positions. Set a station token, or bind to 127.0.0.1."
        ),
    )


def detections_geojson(store: Store) -> dict[str, object]:
    """Current stored detections as a GeoJSON ``FeatureCollection``."""
    return to_geojson(store.all())


def set_status_body(store: Store, detection_id: str, payload: Any) -> tuple[dict[str, Any], int]:
    """Validate a triage request and apply it; return ``(body, status)`` (pure of aiohttp)."""
    if not isinstance(payload, dict):
        return {"error": "expected a JSON object"}, 400
    status = payload.get("status")
    if not isinstance(status, str) or status not in DETECTION_STATUSES:
        return {"error": f"status must be one of {list(DETECTION_STATUSES)}"}, 400
    updated = store.set_status(detection_id, status)
    if updated is None:
        return {"error": "unknown detection id"}, 404
    _log.info("detection_status_set", detection_id=detection_id, status=status)
    return {"id": updated.id, "status": updated.status}, 200


def build_app(
    store: Store,
    *,
    host: str | None = None,
    token: str | None = None,
    block_geojson: dict[str, object] | None = None,
) -> Any:
    """Build the aiohttp station app.

    When ``host`` is given, the fail-closed bind rule is enforced **inside** ``build_app`` (a
    non-loopback bind without a token raises), so the guarantee travels with the app rather than
    relying on the caller. ``/healthz`` stays open; ``/`` (map) and the data/status endpoints
    require the bearer token when one is configured — the page is served with the token injected
    (gated by a ``?token=`` query) so its `fetch` calls can authenticate.
    """
    if host is not None:
        validate_bind(host, token)
    from aiohttp import web

    auth = ServiceAuth("meshsa-scout", token)

    async def index(request: Any) -> Any:
        denied = page_token_gate(auth, request)
        if denied is not None:
            return denied
        return html_page(render_page(token))

    async def detections(_request: Any) -> Any:
        return api_json(detections_geojson(store))

    async def export_csv(_request: Any) -> Any:
        return text_body(to_csv(store.all()), content_type="text/csv")

    async def block(_request: Any) -> Any:
        if block_geojson is None:
            return api_json({"error": "no block loaded"}, status=404)
        return api_json(block_geojson)

    async def set_status(request: Any) -> Any:
        payload = await read_json_or_none(request)
        body, status = set_status_body(store, request.match_info["det_id"], payload)
        return api_json(body, status=status)

    # ``/detections`` and ``/export.geojson`` were byte-identical handlers; one serves both.
    routes: list[tuple[str, str, Handler]] = [
        ("GET", "/", index),
        ("GET", "/healthz", healthz),
        ("GET", "/detections", guarded(auth, detections)),
        ("GET", "/export.geojson", guarded(auth, detections)),
        ("GET", "/export.csv", guarded(auth, export_csv)),
        ("GET", "/block", guarded(auth, block)),
        ("POST", "/detections/{det_id}/status", guarded(auth, set_status)),
    ]
    app = web.Application()
    register_routes(app, routes)
    return app
