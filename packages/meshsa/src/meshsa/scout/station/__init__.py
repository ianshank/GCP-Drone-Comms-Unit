"""Thin operator ground station for scout (aiohttp + MapLibre).

TAK/ATAK is the primary field map (detections flow there via the MARKER→CoT path);
this station adds the vineyard-specific triage TAK lacks: per-pin tag/reject/inspect and
GeoJSON/CSV export over a loopback-default, fail-closed aiohttp app.
"""

from __future__ import annotations

from .app import (
    authorize,
    build_app,
    detections_geojson,
    is_loopback,
    set_status_body,
    validate_bind,
)

__all__ = [
    "build_app",
    "authorize",
    "is_loopback",
    "validate_bind",
    "detections_geojson",
    "set_status_body",
]
