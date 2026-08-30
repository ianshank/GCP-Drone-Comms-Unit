"""The HTTP transport seam: :class:`HttpTransport` + the default aiohttp-backed impl.

Split out of the former flat ``inference.py`` (code-hygiene-modularity T-4.1b).
The network I/O is isolated behind the :class:`HttpTransport` ``Protocol`` so
client-side retry/backoff/parse logic elsewhere in the package is pure and
unit-testable with a fake transport (no sockets, no ``aiohttp`` version
coupling). :class:`AiohttpTransport` is the only socket glue and is the lone
``# pragma: no cover`` here — it owns the ``aiohttp.ClientSession`` (stateful
I/O lives in the transport, not the client; CHARTER §4.4).

``aiohttp`` is an *optional* dependency — install ``meshsa[inference]`` to enable
this default transport. Inject a custom :class:`HttpTransport` and the module
works with no ``aiohttp`` installed at all (the base install is unaffected).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

import structlog

from .errors import InferenceTransportError

# ── Lazy optional import ────────────────────────────────────────────────
try:
    import aiohttp
except ImportError:  # pragma: no cover — optional dependency
    aiohttp = None  # type: ignore[assignment]

_log = structlog.get_logger("meshsa.inference")


@dataclass(frozen=True)
class HttpResponse:
    """A decoded HTTP response: the status and the parsed JSON body."""

    status: int
    payload: dict[str, Any]


@runtime_checkable
class HttpTransport(Protocol):
    """Async POST-JSON seam so the client never touches sockets directly.

    Implementations translate their native errors into
    :class:`InferenceTransportError` for retryable network/timeout failures; any
    HTTP response (success or error) is returned as an :class:`HttpResponse` and
    the caller decides what the status means.
    """

    async def post_json(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        json_body: Mapping[str, Any],
        timeout_s: float,
    ) -> HttpResponse: ...

    async def aclose(self) -> None: ...


def _require_aiohttp() -> None:
    """Raise with an actionable message when aiohttp is absent."""
    if aiohttp is None:
        raise RuntimeError(
            "Nemotron inference requires aiohttp; install 'meshsa[inference]' "
            "or inject a custom HttpTransport"
        )


class AiohttpTransport:
    """Default :class:`HttpTransport` backed by a reused ``aiohttp`` session.

    This is the only socket-bound transport in the module: it owns the
    ``aiohttp.ClientSession`` (created lazily, reused across calls, guarded by an
    ``asyncio.Lock``) and maps ``aiohttp`` errors onto the neutral error model.

    The session is built by ``session_factory``; the default builds a real
    ``aiohttp.ClientSession`` (the lone ``# pragma: no cover`` socket glue), while
    tests inject a fake factory so the reuse/lock/error-mapping logic is covered
    without sockets.
    """

    def __init__(self, *, session_factory: Callable[[], Any] | None = None) -> None:
        self._session_factory = session_factory
        self._session: Any | None = None
        self._session_lock: asyncio.Lock | None = None

    def _new_session(self) -> Any:
        if self._session_factory is not None:
            return self._session_factory()
        return aiohttp.ClientSession()  # pragma: no cover — real socket I/O

    async def _session_for_request(self) -> Any:
        if self._session_lock is None:
            self._session_lock = asyncio.Lock()
        async with self._session_lock:
            if self._session is None or self._session.closed:
                self._session = self._new_session()
            return self._session

    async def post_json(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        json_body: Mapping[str, Any],
        timeout_s: float,
    ) -> HttpResponse:
        _require_aiohttp()
        session = await self._session_for_request()
        timeout = aiohttp.ClientTimeout(total=timeout_s)
        _log.debug("inference_http_request", url=url)
        try:
            async with session.post(
                url, headers=dict(headers), json=dict(json_body), timeout=timeout
            ) as resp:
                status = resp.status
                try:
                    body = await resp.json()
                except (ValueError, aiohttp.ContentTypeError):
                    body = {}
                payload = body if isinstance(body, dict) else {}
                return HttpResponse(status=status, payload=payload)
        except asyncio.TimeoutError as exc:
            raise InferenceTransportError("inference request timed out") from exc
        except aiohttp.ClientError as exc:
            raise InferenceTransportError(str(exc)) from exc

    async def aclose(self) -> None:
        if self._session_lock is None:
            self._session_lock = asyncio.Lock()
        async with self._session_lock:
            # All three logical outcomes are tested (none/open/already-closed); the
            # residual arc coverage flags here is the async-with exception exit.
            if self._session is not None and not self._session.closed:  # pragma: no branch
                await self._session.close()
                self._session = None
