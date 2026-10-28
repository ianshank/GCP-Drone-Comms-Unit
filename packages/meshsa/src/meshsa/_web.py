"""Shared aiohttp service kit — the HTTP auth/response primitives the app factories share.

``ui/app.py``, ``scout/station/app.py``, ``llm/server.py`` and ``health.py`` each used to
inline the same bearer check, 401 body, ``Cache-Control: no-store`` policy and JSON-body
parsing (design D-5 of ``openspec/changes/code-hygiene-modularity``). Four copies drifted:
only the console sent ``no-store`` and only the health listener sent the RFC 7235
``WWW-Authenticate`` challenge. This module is the single audited copy; the factories keep
only their route tables.

Deliberately **out of scope**: bind validation. Each factory keeps its own six-line
``validate_bind`` adapter over :func:`meshsa.netauth.validate_bind` — that direct-delegating
shape is exactly what ``tools/claude_hooks/bind_guard.py`` recognises (design D-4), and a
third module in the chain would blind it.

``aiohttp`` is imported inside each response helper, never at module import, so importing
``meshsa`` (or any factory module) does not require the ``[ui]``/``[llm]``/``[health]`` extra —
the same rule the factories already follow.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from .netauth import authorize

__all__ = [
    "NO_STORE_HEADERS",
    "UNAUTHORIZED_BODY",
    "Handler",
    "ServiceAuth",
    "api_json",
    "bearer_guard",
    "guarded",
    "healthz",
    "html_page",
    "normalize_token",
    "page_token_gate",
    "read_json_or_none",
    "register_routes",
    "text_body",
    "unauthorized",
    "upstream_error",
]

#: An aiohttp request handler. Typed loosely so the factories stay importable without aiohttp.
Handler = Callable[[Any], Awaitable[Any]]

#: Every credential-bearing response carries this: an intermediary proxy must never persist
#: an authorized payload for replay to an unauthenticated client (spec delta
#: ``m2-bind-safety`` "Authenticated JSON Responses Are Non-Cacheable").
NO_STORE_HEADERS: Mapping[str, str] = MappingProxyType({"Cache-Control": "no-store"})

#: The one refusal body, house-wide: no detail, no partial data. Both constants are
#: read-only views so no importer can change every 401 or every cache header by mutation.
UNAUTHORIZED_BODY: Mapping[str, str] = MappingProxyType({"error": "unauthorized"})


def normalize_token(token: str | None) -> str | None:
    """``""``/whitespace → ``None``: an empty credential is no credential.

    The rule ``UIConfig`` applies at load and ``llm/server.resolve_config`` applies to
    ``MESHSA_LLM_TOKEN``. A factory that normalises must do so **before** its bind check
    (``build_ui_app`` does), so the fail-closed check and the bearer guard see the same
    value; :class:`ServiceAuth` itself never normalises — see its docstring.
    """
    if token is None:
        return None
    return token.strip() or None


@dataclass(frozen=True)
class ServiceAuth:
    """A service's bearer posture: its realm name and its token, **verbatim**.

    ``token`` is ``None``/``""`` for open — :func:`meshsa.netauth.authorize` admits every
    request, and loopback-only exposure is enforced separately by the factory's
    ``validate_bind`` adapter. Anything else is a configured credential, exactly as
    ``netauth.validate_bind``'s ``not token`` guard sees it: the kit must never treat as
    *open* a token the bind check accepted as a *credential*. So a whitespace-only token is
    carried as is — ``authorize`` strips only the presented bearer, so such a token is
    unmatchable (every request is refused; the documented pre-existing semantics, see
    ``docs/NEXTSTEPS.md`` "whitespace-only bearer tokens") rather than silently open.
    Normalising belongs to the caller, before its bind check (:func:`normalize_token`).
    """

    service: str
    token: str | None

    @property
    def challenge(self) -> str:
        """The RFC 7235 §3.1 ``WWW-Authenticate`` value a 401 from this service carries."""
        return f'Bearer realm="{self.service}"'

    def allows(self, auth_header: str | None) -> bool:
        """Whether a request presenting ``Authorization: <auth_header>`` may proceed."""
        return authorize(self.token, auth_header)

    def allows_query_token(self, presented: str | None) -> bool:
        """The page-navigation form: a ``?token=`` query checked exactly like a bearer."""
        return authorize(self.token, "Bearer " + (presented or ""))


def unauthorized(auth: ServiceAuth) -> Any:
    """The single 401: generic body, ``no-store``, and the service's bearer challenge."""
    from aiohttp import web

    return web.json_response(
        dict(UNAUTHORIZED_BODY),
        status=401,
        headers={**NO_STORE_HEADERS, "WWW-Authenticate": auth.challenge},
    )


def bearer_guard(auth: ServiceAuth, request: Any) -> Any | None:
    """``None`` when the request's ``Authorization`` header is accepted, else the 401."""
    if auth.allows(request.headers.get("Authorization")):
        return None
    return unauthorized(auth)


def page_token_gate(auth: ServiceAuth, request: Any) -> Any | None:
    """The HTML-page variant of :func:`bearer_guard`, gated on a ``?token=`` query.

    Browsers cannot set an ``Authorization`` header on navigation, so operator pages are
    reached with the token in the query and then served with it injected for their
    ``fetch`` calls (the station pattern). Open when no token is configured.
    """
    if auth.allows_query_token(request.query.get("token")):
        return None
    return unauthorized(auth)


def guarded(auth: ServiceAuth, handler: Handler) -> Handler:
    """Wrap ``handler`` so it runs only past :func:`bearer_guard`."""

    async def _guarded(request: Any) -> Any:
        denied = bearer_guard(auth, request)
        if denied is not None:
            return denied
        return await handler(request)

    return _guarded


def api_json(body: Any, *, status: int = 200) -> Any:
    """A JSON response that an intermediary must not cache."""
    from aiohttp import web

    return web.json_response(body, status=status, headers=dict(NO_STORE_HEADERS))


def text_body(text: str, *, content_type: str, status: int = 200) -> Any:
    """A text response (CSV export, Prometheus exposition) that an intermediary must not cache."""
    from aiohttp import web

    return web.Response(
        text=text, content_type=content_type, status=status, headers=dict(NO_STORE_HEADERS)
    )


def html_page(page: str) -> Any:
    """An operator page: ``text/html`` and ``no-store`` (it embeds the bearer token)."""
    return text_body(page, content_type="text/html")


async def read_json_or_none(
    request: Any, *, log: Any | None = None, route: str = "", event: str = "json_body_parse_error"
) -> Any | None:
    """The request's JSON body, or ``None`` when there is none or it does not parse.

    Callers turn ``None`` into their own 400 (the pure ``*_body`` helpers already do), so a
    malformed body is a client error, never a 500. With ``log`` given, the parse failure is
    recorded server-side (``route``/``error``/``error_type``) so a client sending garbage
    is diagnosable without ever echoing the body back.
    """
    try:
        return await request.json()
    except Exception as exc:
        if log is not None:
            log.warning(event, route=route, error=str(exc), error_type=type(exc).__name__)
        return None


async def healthz(_request: Any) -> Any:
    """The open ``{"status": "ok"}`` liveness route of the console, station and llm server.

    ``health.py`` keeps its own open ``/healthz`` that serves the node snapshot (audit row
    #7); this one discloses nothing.
    """
    from aiohttp import web

    return web.json_response({"status": "ok"})


def upstream_error(
    log: Any, route: str, exc: Exception, *, message: str, event: str = "upstream_error"
) -> Any:
    """A generic 502 for a raising data source: detail server-side only (the llm policy)."""
    log.warning(event, route=route, error=str(exc), error_type=type(exc).__name__)
    return api_json({"error": message}, status=502)


def register_routes(app: Any, routes: Iterable[tuple[str, str, Handler]]) -> None:
    """Wire a ``(method, path, handler)`` table — the factory's whole remaining job.

    GET entries go through ``add_get`` so aiohttp keeps registering the implicit HEAD
    alongside them, exactly as the factories did before the kit (a load balancer probing
    ``HEAD /healthz`` must keep getting 200, not 405).
    """
    for method, path, handler in routes:
        if method == "GET":
            app.router.add_get(path, handler)
        else:
            app.router.add_route(method, path, handler)
