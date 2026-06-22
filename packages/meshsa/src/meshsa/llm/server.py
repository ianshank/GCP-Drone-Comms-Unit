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

import hmac
import os
from collections.abc import Mapping
from typing import Any, Protocol

import structlog
from pydantic import BaseModel

from .._parsing import parse_int
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

#: Max accepted chat prompt length. The endpoint can be exposed off-loopback (with a
#: token) and each prompt spends model tokens, so an unbounded prompt is a cost/latency
#: DoS. Generous for real SA questions; oversized prompts get a 400, not a model call.
DEFAULT_MAX_PROMPT_CHARS = 8000
MAX_PROMPT_CHARS = DEFAULT_MAX_PROMPT_CHARS
ENV_MAX_PROMPT_CHARS = "MESHSA_LLM_MAX_PROMPT_CHARS"

# Server bind defaults + the environment-variable names that override every
# setting. Centralized so there are no scattered magic strings/ports.
# Default bind is loopback: the ``/chat`` endpoint discloses live drone/track
# positions and spends model tokens, so it must never be reachable off-host
# unless the operator opts in *and* sets ``MESHSA_LLM_TOKEN`` (see validate_bind).
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8090
ENV_HOST = "MESHSA_LLM_HOST"
ENV_PORT = "MESHSA_LLM_PORT"
ENV_TOKEN = "MESHSA_LLM_TOKEN"
ENV_MAVLINK2REST_URL = "MESHSA_MAVLINK2REST_URL"
ENV_DRONE_UID = "MESHSA_DRONE_UID"
ENV_FTS_TRACKS_URL = "MESHSA_FTS_TRACKS_URL"

#: Hosts treated as loopback-only (safe to serve without a bearer token).
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


class ServerConfig(BaseModel):
    """Resolved runtime configuration for the SA-assistant server."""

    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    token: str | None = None
    mavlink2rest_url: str = DEFAULT_MAVLINK2REST_URL
    drone_uid: str = DEFAULT_DRONE_UID
    fts_tracks_url: str = DEFAULT_FTS_TRACKS_URL
    max_prompt_chars: int = DEFAULT_MAX_PROMPT_CHARS


def resolve_config(env: Mapping[str, str]) -> ServerConfig:
    """Build a :class:`ServerConfig` from an environment mapping (pure/testable).

    Every field falls back to its module-level default when the corresponding
    ``MESHSA_*`` variable is unset; ``port`` is parsed to ``int``. An empty,
    whitespace-only, or unset ``MESHSA_LLM_TOKEN`` resolves to ``None`` (no
    token). Surrounding whitespace is stripped so a secret sourced from a file
    or here-doc with a trailing newline still matches the bearer presented by a
    client (which :func:`authorize` strips symmetrically).
    """
    token = (env.get(ENV_TOKEN) or "").strip() or None
    return ServerConfig(
        host=env.get(ENV_HOST, DEFAULT_HOST),
        port=parse_int(ENV_PORT, env.get(ENV_PORT, str(DEFAULT_PORT)), lo=1, hi=65535),
        token=token,
        mavlink2rest_url=env.get(ENV_MAVLINK2REST_URL, DEFAULT_MAVLINK2REST_URL),
        drone_uid=env.get(ENV_DRONE_UID, DEFAULT_DRONE_UID),
        fts_tracks_url=env.get(ENV_FTS_TRACKS_URL, DEFAULT_FTS_TRACKS_URL),
        max_prompt_chars=parse_int(
            ENV_MAX_PROMPT_CHARS,
            env.get(ENV_MAX_PROMPT_CHARS, str(DEFAULT_MAX_PROMPT_CHARS)),
            lo=1,
        ),
    )


def is_loopback(host: str) -> bool:
    """True when ``host`` is a loopback bind that needs no network auth."""
    return host.strip().lower() in _LOOPBACK_HOSTS


def authorize(token: str | None, auth_header: str | None) -> bool:
    """Return whether a request may proceed (pure; no web framework).

    When no ``token`` is configured the endpoint is open (loopback is enforced
    separately by :func:`validate_bind`). When a token is set, require a
    constant-time-matching ``Authorization: Bearer <token>`` header.

    The comparison runs on UTF-8 bytes, not ``str``: ``hmac.compare_digest``
    raises ``TypeError`` on non-ASCII ``str`` operands, so a client-supplied
    (or operator-configured) non-ASCII token would otherwise crash the auth
    check into a 500 instead of yielding a clean ``False``.
    """
    if token is None:
        return True
    if not auth_header:
        return False
    scheme, _, presented = auth_header.partition(" ")
    if scheme.lower() != "bearer" or not presented:
        return False
    return hmac.compare_digest(presented.strip().encode("utf-8"), token.encode("utf-8"))


def validate_bind(host: str, token: str | None) -> None:
    """Fail closed: a non-loopback bind without a token is a misconfiguration.

    Raises :class:`ValueError` so the entry point can refuse to start rather than
    silently exposing an unauthenticated assistant to the network.
    """
    if not is_loopback(host) and token is None:
        raise ValueError(
            f"refusing to bind meshsa-llm to {host!r} without {ENV_TOKEN} set: the "
            "assistant discloses live positions and spends model tokens. Set "
            f"{ENV_TOKEN} to a strong secret, or bind to 127.0.0.1."
        )


class _Agent(Protocol):
    async def ask(self, prompt: str, history: list[dict[str, Any]] | None = None) -> AgentReply: ...


async def chat_reply(
    agent: _Agent,
    payload: Any,
    max_prompt_chars: int = DEFAULT_MAX_PROMPT_CHARS,
) -> tuple[dict[str, Any], int]:
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
    if len(prompt) > max_prompt_chars:
        return {"error": f"prompt too long (max {max_prompt_chars} chars)"}, 400
    try:
        reply = await agent.ask(prompt.strip())
    except Exception as exc:
        _log.warning("sa_assistant_error", error=str(exc), error_type=type(exc).__name__)
        return {"error": _UPSTREAM_ERROR}, 502
    return {"reply": reply.text, "tools": reply.tool_calls, "stop_reason": reply.stop_reason}, 200


def build_app(
    agent: _Agent,
    token: str | None = None,
    max_prompt_chars: int = DEFAULT_MAX_PROMPT_CHARS,
) -> Any:
    """Build the aiohttp application serving the widget and chat endpoint.

    When ``token`` is set, ``/chat`` requires ``Authorization: Bearer <token>``.
    The static widget (``/``) and ``/healthz`` stay open — neither discloses
    telemetry; the data + token-spend surface is ``/chat`` alone.
    """
    from aiohttp import web

    async def index(_request: Any) -> Any:
        return web.Response(text=CHAT_WIDGET_HTML, content_type="text/html")

    async def chat(request: Any) -> Any:
        if not authorize(token, request.headers.get("Authorization")):
            return web.json_response({"error": "unauthorized"}, status=401)
        try:
            payload = await request.json()
        except Exception:
            payload = None
        body, status = await chat_reply(agent, payload, max_prompt_chars=max_prompt_chars)
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
    validate_bind(cfg.host, cfg.token)  # fail closed before opening a socket
    telemetry = Mavlink2RestSource(cfg.mavlink2rest_url, uid=cfg.drone_uid)
    tracks = FtsTrackSource(cfg.fts_tracks_url)
    agent = build_agent(telemetry, tracks)
    web.run_app(
        build_app(agent, cfg.token, max_prompt_chars=cfg.max_prompt_chars),
        host=cfg.host,
        port=cfg.port,
    )


if __name__ == "__main__":  # pragma: no cover
    main()
