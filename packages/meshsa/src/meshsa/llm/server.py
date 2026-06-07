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
from typing import Any, Protocol

import structlog

from .agent import AgentReply
from .widget import CHAT_WIDGET_HTML

_log = structlog.get_logger(__name__)

#: Stable, non-sensitive message returned to the browser on an upstream failure.
_UPSTREAM_ERROR = "assistant unavailable; check the server logs"


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
    Requires the ``[llm]`` extra and ``ANTHROPIC_API_KEY``.
    """
    from aiohttp import web

    from .agent import build_agent
    from .sources import FtsTrackSource, Mavlink2RestSource

    host = os.environ.get("MESHSA_LLM_HOST", "0.0.0.0")
    port = int(os.environ.get("MESHSA_LLM_PORT", "8090"))
    telemetry = Mavlink2RestSource(
        os.environ.get("MESHSA_MAVLINK2REST_URL", "http://127.0.0.1:8088"),
        uid=os.environ.get("MESHSA_DRONE_UID", "uav-1"),
    )
    tracks = FtsTrackSource(
        os.environ.get(
            "MESHSA_FTS_TRACKS_URL",
            "http://127.0.0.1:19023/ManageGeoObject/getCoTGeoObject",
        )
    )
    agent = build_agent(telemetry, tracks)
    web.run_app(build_app(agent), host=host, port=port)


if __name__ == "__main__":  # pragma: no cover
    main()
