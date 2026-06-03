"""Opt-in health/observability surface.

``health_snapshot`` is a pure function (no I/O) that renders a node's router
metrics and per-transport counters as a plain dict — fully unit-tested.

``serve_healthz`` starts a tiny aiohttp listener exposing that snapshot at
``/healthz``. ``aiohttp`` is imported **inside** the function so importing this
module never requires it; install the ``[health]`` extra to use the server.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .node import Node


def health_snapshot(node: Node) -> dict[str, Any]:
    """Render router metrics + per-transport counters as a JSON-able dict."""
    m = node.router.metrics
    transports = {
        t.name: {
            "dropped_inbox_full": getattr(t, "dropped_inbox_full", 0),
            "reconnects": getattr(t, "reconnects", 0),
        }
        for t in node.router.transports
    }
    return {
        "status": "ok",
        "uid": node.info.uid,
        "metrics": {
            "rx": m.rx,
            "tx": m.tx,
            "forwarded": m.forwarded,
            "dropped_undecodable": m.dropped_undecodable,
            "schema_mismatch": m.schema_mismatch,
        },
        "transports": transports,
    }


async def serve_healthz(node: Node, host: str, port: int) -> Any:  # pragma: no cover - real server
    """Start an aiohttp ``/healthz`` listener; returns the runner (call cleanup)."""
    from aiohttp import web

    async def handler(_request: Any) -> Any:
        return web.json_response(health_snapshot(node))

    app = web.Application()
    app.router.add_get("/healthz", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, host, port).start()
    return runner
