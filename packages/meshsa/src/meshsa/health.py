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
from .netauth import authorize
from .netauth import validate_bind as _validate_bind

if TYPE_CHECKING:
    from .config import HealthConfig
    from .node import Node


def validate_healthz_bind(host: str, token: str | None) -> None:
    """Fail closed: a non-loopback ``/healthz``+``/metrics`` bind without a token is a misconfig.

    ``/metrics`` discloses router/transport/inference counters, so a non-loopback bind must carry a
    bearer token. Delegates to the shared ``netauth`` primitive (mirrors ``meshsa.llm.server`` and
    the scout station), and is pure (no aiohttp) so it is unit-tested directly.
    """
    _validate_bind(
        host,
        token,
        service="meshsa-healthz",
        remedy="the /metrics surface discloses counters. Set health.token / MESHSA_HEALTH_TOKEN, "
        "or bind to 127.0.0.1.",
    )


def _resolve_metrics_options(
    node: Node,
    metrics_enabled: bool | None,
    metrics_path: str | None,
    metrics_format: Literal["prometheus", "json"] | None,
) -> tuple[bool, str, Literal["prometheus", "json"]]:
    """Fill any unset ``serve_healthz`` metrics arg from ``node.config.health.*``.

    An explicit (non-``None``) argument always wins; otherwise the value falls
    back to the node config so setting ``health.metrics_enabled=true`` exposes
    ``/metrics`` with no CLI change. Pure/branching logic kept out of the
    pragma-excluded aiohttp wiring so it is testable.
    """
    health: HealthConfig = node.config.health
    enabled = health.metrics_enabled if metrics_enabled is None else metrics_enabled
    path = health.metrics_path if metrics_path is None else metrics_path
    fmt = health.metrics_format if metrics_format is None else metrics_format
    return enabled, path, fmt


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

    When ``node.inference_service`` is set (``config.inference.enabled=true``),
    its counters (:meth:`InferenceService.as_dict`) are included as
    ``body["inference"]`` for json or ``meshsa_inference_*`` lines for
    Prometheus. When inference is disabled the key/lines are omitted entirely,
    so existing callers see byte-identical output (backward compatible).
    """
    inference = node.inference_service.as_dict() if node.inference_service else None
    if fmt == "json":
        body: dict[str, Any] = {
            "metrics": node.router.metrics.as_dict(),
            "transports": _transport_counters(node),
        }
        if inference is not None:
            body["inference"] = inference
        return body
    return render_prometheus(node.router.metrics, _transport_counters(node), inference=inference)


def build_healthz_app(
    node: Node,
    *,
    token: str | None,
    metrics_enabled: bool,
    metrics_path: str,
    metrics_format: Literal["prometheus", "json"],
) -> Any:
    """Build the aiohttp ``/healthz`` (+ opt-in ``/metrics``) application.

    ``/healthz`` is open (liveness), matching the other services. ``/metrics`` requires
    ``Authorization: Bearer <token>`` when a ``token`` is set (it discloses router/transport/
    inference counters); with no token it stays open (loopback-default). The auth branch lives
    **here**, in this testable factory, not in the pragma-excluded ``serve_healthz`` wiring — so a
    real request exercises it (mirrors ``scout.station.build_app`` / ``meshsa.llm.server.build_app``).
    """
    from aiohttp import web

    async def healthz(_request: Any) -> Any:
        return web.json_response(health_snapshot(node))

    app = web.Application()
    app.router.add_get("/healthz", healthz)

    if metrics_enabled:

        async def metrics_handler(request: Any) -> Any:
            if not authorize(token, request.headers.get("Authorization")):
                return web.json_response({"error": "unauthorized"}, status=401)
            body = render_metrics(node, metrics_format)
            if isinstance(body, str):
                return web.Response(text=body, content_type="text/plain")
            return web.json_response(body)

        app.router.add_get(metrics_path, metrics_handler)

    return app


async def serve_healthz(
    node: Node,
    host: str,
    port: int,
    *,
    token: str | None = None,
    metrics_enabled: bool | None = None,
    metrics_path: str | None = None,
    metrics_format: Literal["prometheus", "json"] | None = None,
) -> Any:  # pragma: no cover - real server
    """Start an aiohttp ``/healthz`` (and opt-in ``/metrics``) listener.

    Returns the runner (call ``cleanup``). ``token`` defaults from ``node.config.health.token``;
    the bind is validated fail-closed first (a non-loopback bind without a token is refused). The
    metrics args default from ``node.config.health.*`` when left unset, so ``health.metrics_enabled=
    true`` exposes ``/metrics`` with no CLI change. The routing/auth/rendering all live in pure,
    tested helpers (``build_healthz_app``/``validate_healthz_bind``/``render_metrics``); only the
    socket wiring here is pragma-excluded.
    """
    from aiohttp import web

    if token is None:
        token = node.config.health.token
    validate_healthz_bind(host, token)
    metrics_enabled, metrics_path, metrics_format = _resolve_metrics_options(
        node, metrics_enabled, metrics_path, metrics_format
    )
    app = build_healthz_app(
        node,
        token=token,
        metrics_enabled=metrics_enabled,
        metrics_path=metrics_path,
        metrics_format=metrics_format,
    )
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, host, port).start()
    return runner
