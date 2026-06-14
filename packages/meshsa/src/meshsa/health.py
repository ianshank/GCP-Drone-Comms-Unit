"""Opt-in health/observability surface.

``health_snapshot`` is a pure function (no I/O) that renders a node's router
metrics and per-transport counters as a plain dict — fully unit-tested.

``serve_healthz`` starts a tiny aiohttp listener exposing that snapshot at
``/healthz``. ``aiohttp`` is imported **inside** the function so importing this
module never requires it; install the ``[health]`` extra to use the server.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from .metrics import render_prometheus

if TYPE_CHECKING:
    from .node import Node


def _transport_counters(node: Node) -> dict[str, dict[str, int]]:
    """Per-transport counters keyed by transport name (missing keys -> ``0``)."""
    return {
        t.name: {
            "dropped_inbox_full": getattr(t, "dropped_inbox_full", 0),
            "reconnects": getattr(t, "reconnects", 0),
            "rx_frames": getattr(t, "rx_frames", 0),
        }
        for t in node.router.transports
    }


def health_snapshot(node: Node) -> dict[str, Any]:
    """Render router metrics + per-transport counters as a JSON-able dict."""
    m = node.router.metrics
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
        "transports": _transport_counters(node),
    }


def render_metrics(node: Node, fmt: Literal["prometheus", "json"]) -> str | dict[str, Any]:
    """Render the metrics body for the requested format (pure, fully tested).

    Returns Prometheus text for ``"prometheus"`` or a JSON-able dict (router
    counters + per-transport counters) for ``"json"``. The aiohttp ``/metrics``
    seam serves whichever this returns; all branch logic lives here, not in the
    pragma-excluded wiring.
    """
    if fmt == "json":
        return {
            "metrics": node.router.metrics.as_dict(),
            "transports": _transport_counters(node),
        }
    return render_prometheus(node.router.metrics, _transport_counters(node))


async def serve_healthz(
    node: Node,
    host: str,
    port: int,
    *,
    metrics_enabled: bool = False,
    metrics_path: str = "/metrics",
    metrics_format: Literal["prometheus", "json"] = "prometheus",
) -> Any:  # pragma: no cover - real server
    """Start an aiohttp ``/healthz`` (and opt-in ``/metrics``) listener.

    Returns the runner (call ``cleanup``). The snapshot/metrics rendering lives in
    pure helpers above; only the aiohttp wiring here is pragma-excluded.
    """
    from aiohttp import web

    async def handler(_request: Any) -> Any:
        return web.json_response(health_snapshot(node))

    app = web.Application()
    app.router.add_get("/healthz", handler)

    if metrics_enabled:

        async def metrics_handler(_request: Any) -> Any:
            body = render_metrics(node, metrics_format)
            if isinstance(body, str):
                return web.Response(text=body, content_type="text/plain")
            return web.json_response(body)

        app.router.add_get(metrics_path, metrics_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, host, port).start()
    return runner
