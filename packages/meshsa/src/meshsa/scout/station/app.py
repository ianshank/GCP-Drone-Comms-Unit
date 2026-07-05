"""aiohttp station: serve pins, triage, and exports over a fail-closed app.

Pure helpers (``authorize``/``is_loopback``/``validate_bind``/``detections_geojson``/
``set_status_body``) are unit-tested without a web framework; ``build_app`` wires them into
aiohttp routes. Data + mutation endpoints require ``Authorization: Bearer <token>`` when a
token is set; a non-loopback bind without a token is refused (fail-closed), mirroring
``meshsa.llm.server``.
"""

from __future__ import annotations

from typing import Any

import structlog

from ...netauth import authorize, is_loopback
from ...netauth import validate_bind as _validate_bind
from ..protocols import Store
from ..schemas import DETECTION_STATUSES
from ..store import to_csv, to_geojson
from ._html import MAP_HTML

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
    token: str | None = None,
    block_geojson: dict[str, object] | None = None,
) -> Any:
    """Build the aiohttp station app.

    ``/`` (map) and ``/healthz`` stay open; ``/detections``, ``/export.*``, ``/block`` and the
    status POST require the bearer token when one is configured.
    """
    from aiohttp import web

    def _guard(request: Any) -> Any | None:
        if not authorize(token, request.headers.get("Authorization")):
            return web.json_response({"error": "unauthorized"}, status=401)
        return None

    async def index(_request: Any) -> Any:
        return web.Response(text=MAP_HTML, content_type="text/html")

    async def healthz(_request: Any) -> Any:
        return web.json_response({"status": "ok"})

    async def detections(request: Any) -> Any:
        denied = _guard(request)
        if denied is not None:
            return denied
        return web.json_response(detections_geojson(store))

    async def export_geojson(request: Any) -> Any:
        denied = _guard(request)
        if denied is not None:
            return denied
        return web.json_response(detections_geojson(store))

    async def export_csv(request: Any) -> Any:
        denied = _guard(request)
        if denied is not None:
            return denied
        return web.Response(text=to_csv(store.all()), content_type="text/csv")

    async def block(request: Any) -> Any:
        denied = _guard(request)
        if denied is not None:
            return denied
        if block_geojson is None:
            return web.json_response({"error": "no block loaded"}, status=404)
        return web.json_response(block_geojson)

    async def set_status(request: Any) -> Any:
        denied = _guard(request)
        if denied is not None:
            return denied
        try:
            payload = await request.json()
        except Exception:
            payload = None
        body, status = set_status_body(store, request.match_info["det_id"], payload)
        return web.json_response(body, status=status)

    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/healthz", healthz)
    app.router.add_get("/detections", detections)
    app.router.add_get("/export.geojson", export_geojson)
    app.router.add_get("/export.csv", export_csv)
    app.router.add_get("/block", block)
    app.router.add_post("/detections/{det_id}/status", set_status)
    return app
