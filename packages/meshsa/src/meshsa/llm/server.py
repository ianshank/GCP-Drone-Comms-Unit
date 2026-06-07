"""Tiny aiohttp server exposing the SA assistant as a chat endpoint + widget.

Routes:
  * ``GET  /``        -> the self-contained chat widget (for a Cockpit iframe)
  * ``POST /chat``    -> ``{"prompt": "..."}`` -> ``{"reply": "...", "tools": [...]}``
  * ``GET  /healthz`` -> ``{"status": "ok"}``

The request-handling logic is factored into :func:`chat_reply`, a pure-ish
coroutine that is unit-tested with a fake agent. ``aiohttp`` and ``anthropic``
are imported lazily, mirroring ``meshsa.health`` — importing this module never
requires the ``[llm]`` extra.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any, Protocol

import structlog
from pydantic import BaseModel

from .agent import AgentReply
from .sources import (
    DEFAULT_DRONE_UID,
    DEFAULT_FTS_TRACKS_URL,
    DEFAULT_MAVLINK2REST_URL,
)
from .widget import CHAT_WIDGET_HTML

_log = structlog.get_logger(__name__)

#: Stable, non-sensitive message returned to the browser on an upstream failure.
_UPSTREAM_ERROR = "assistant unavailable; check the server logs"

# Server bind defaults + the environment-variable names that override every
# setting. Centralized so there are no scattered magic strings/ports.
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8090
ENV_HOST = "MESHSA_LLM_HOST"
ENV_PORT = "MESHSA_LLM_PORT"
ENV_MAVLINK2REST_URL = "MESHSA_MAVLINK2REST_URL"
ENV_DRONE_UID = "MESHSA_DRONE_UID"
ENV_FTS_TRACKS_URL = "MESHSA_FTS_TRACKS_URL"


class ServerConfig(BaseModel):
    """Resolved runtime configuration for the SA-assistant server."""

    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    mavlink2rest_url: str = DEFAULT_MAVLINK2REST_URL
    drone_uid: str = DEFAULT_DRONE_UID
    fts_tracks_url: str = DEFAULT_FTS_TRACKS_URL


def resolve_config(env: Mapping[str, str]) -> ServerConfig:
    """Build a :class:`ServerConfig` from an environment mapping (pure/testable).

    Every field falls back to its module-level default when the corresponding
    ``MESHSA_*`` variable is unset; ``port`` is parsed to ``int``.
    """
    return ServerConfig(
        host=env.get(ENV_HOST, DEFAULT_HOST),
        port=int(env.get(ENV_PORT, str(DEFAULT_PORT))),
        mavlink2rest_url=env.get(ENV_MAVLINK2REST_URL, DEFAULT_MAVLINK2REST_URL),
        drone_uid=env.get(ENV_DRONE_UID, DEFAULT_DRONE_UID),
        fts_tracks_url=env.get(ENV_FTS_TRACKS_URL, DEFAULT_FTS_TRACKS_URL),
    )


class _Agent(Protocol):
    async def ask(self, prompt: str, history: list[dict[str, Any]] | None = None) -> AgentReply: ...


async def chat_reply(agent: _Agent, payload: Any) -> tuple[dict[str, Any], int]:
    """Validate a chat payload, run the agent, and return ``(body, status)``.

    Pure of any web framework: tested directly with a fake agent. A missing or
    empty ``prompt`` yields a 400; an upstream model/transport error yields a 502
    with a **generic** message (the detail is logged server-side, never returned
    to the browser, so internal URLs/IDs can't leak).
    """
    if not isinstance(payload, dict):
        return {"error": "expected a JSON object"}, 400
    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        return {"error": "missing 'prompt'"}, 400
    try:
        reply = await agent.ask(prompt.strip())
    except Exception as exc:
        _log.warning("sa_assistant_error", error=str(exc), error_type=type(exc).__name__)
        return {"error": _UPSTREAM_ERROR}, 502
    return {"reply": reply.text, "tools": reply.tool_calls, "stop_reason": reply.stop_reason}, 200


def build_app(agent: _Agent) -> Any:  # pragma: no cover - real aiohttp wiring
    """Build the aiohttp application serving the widget and chat endpoint."""
    from aiohttp import web

    async def index(_request: Any) -> Any:
        return web.Response(text=CHAT_WIDGET_HTML, content_type="text/html")

    async def chat(request: Any) -> Any:
        try:
            payload = await request.json()
        except Exception:
            payload = None
        body, status = await chat_reply(agent, payload)
        return web.json_response(body, status=status)

    async def healthz(_request: Any) -> Any:
        return web.json_response({"status": "ok"})

    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_post("/chat", chat)
    app.router.add_get("/healthz", healthz)
    return app


def main() -> None:  # pragma: no cover - process entry point
    """Console entry point (``meshsa-llm``): serve the SA assistant.

    Wires real HTTP sources from the environment and the real Anthropic client.
    Requires the ``[llm]`` extra and ``ANTHROPIC_API_KEY``. Missing optional
    dependencies produce a clear install hint rather than a raw import traceback.
    """
    try:
        import aiohttp  # noqa: F401  # presence check; web imported below
        import anthropic  # noqa: F401  # presence check; used lazily by build_agent
    except ImportError as exc:
        raise SystemExit(
            "meshsa-llm needs the optional [llm] extra (aiohttp + anthropic).\n"
            "Install it with:  pip install -e 'packages/meshsa[llm]'\n"
            f"(missing dependency: {exc.name})"
        ) from exc

    from aiohttp import web

    from .agent import build_agent
    from .sources import FtsTrackSource, Mavlink2RestSource

    cfg = resolve_config(os.environ)
    telemetry = Mavlink2RestSource(cfg.mavlink2rest_url, uid=cfg.drone_uid)
    tracks = FtsTrackSource(cfg.fts_tracks_url)
    agent = build_agent(telemetry, tracks)
    web.run_app(build_app(agent), host=cfg.host, port=cfg.port)


if __name__ == "__main__":  # pragma: no cover
    main()
