"""Nemotron Ultra Inference Layer.

Provides AI-driven analysis of situational-awareness messages by bridging
the mesh network to NVIDIA's OpenAI-compatible NIM API.

The network I/O is isolated behind the :class:`HttpTransport` ``Protocol`` so the
retry/backoff/parse logic in :class:`NemotronClient` is pure and unit-testable with
a fake transport (no sockets, no ``aiohttp`` version coupling). The default
:class:`AiohttpTransport` is the only socket glue and is the lone ``# pragma: no
cover`` here — it owns the ``aiohttp.ClientSession`` (stateful I/O lives in the
transport, not the client; CHARTER §4.4).

``aiohttp`` is an *optional* dependency — install ``meshsa[inference]`` to enable
the default transport. Inject a custom :class:`HttpTransport` and the module works
with no ``aiohttp`` installed at all (the base install is unaffected).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

import structlog
from pydantic import BaseModel

from .config import NemotronConfig
from .errors import MeshSAError
from .models import ChatPayload, Envelope, MessageKind
from .protocols import Clock, IdFactory
from .router import Router
from .version import SCHEMA_VERSION

# ── Lazy optional import ────────────────────────────────────────────────
try:
    import aiohttp
except ImportError:  # pragma: no cover — optional dependency
    aiohttp = None  # type: ignore[assignment]

_log = structlog.get_logger("meshsa.inference")

# Default prefix applied to all AI-generated messages.  Used by
# ``_is_ai_insight`` to prevent multi-node feedback loops.
_DEFAULT_INSIGHT_PREFIX = "[AI Insight]"

#: HTTP status that signals upstream rate limiting (retried with backoff).
_HTTP_TOO_MANY_REQUESTS = 429
#: First HTTP status considered an error response.
_HTTP_ERROR_FLOOR = 400


# ── Errors (neutral, transport-agnostic) ────────────────────────────────
class InferenceError(MeshSAError):
    """Base class for inference-layer failures."""


class InferenceTransportError(InferenceError):
    """A transport-level failure (timeout, connection reset) — retryable."""


class InferenceHttpError(InferenceError):
    """A non-success HTTP response that survived the retry budget."""

    def __init__(self, status: int, message: str = "") -> None:
        self.status = status
        super().__init__(message or f"inference HTTP {status}")


# ── HTTP seam ───────────────────────────────────────────────────────────
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
        raise RuntimeError(  # pragma: no cover — only when aiohttp absent
            "Nemotron inference requires aiohttp; install 'meshsa[inference]' "
            "or inject a custom HttpTransport"
        )


class AiohttpTransport:
    """Default :class:`HttpTransport` backed by a reused ``aiohttp`` session.

    This is the only socket glue in the module: it owns the
    ``aiohttp.ClientSession`` (created lazily, reused across calls, guarded by an
    ``asyncio.Lock``) and maps ``aiohttp`` errors onto the neutral error model.
    """

    def __init__(self) -> None:
        self._session: Any | None = None
        self._session_lock: asyncio.Lock | None = None

    async def post_json(  # pragma: no cover — real socket I/O
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        json_body: Mapping[str, Any],
        timeout_s: float,
    ) -> HttpResponse:
        _require_aiohttp()
        if self._session_lock is None:
            self._session_lock = asyncio.Lock()
        async with self._session_lock:
            if self._session is None or self._session.closed:
                self._session = aiohttp.ClientSession()
            session = self._session

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

    async def aclose(self) -> None:  # pragma: no cover — real socket I/O
        if self._session_lock is None:
            self._session_lock = asyncio.Lock()
        async with self._session_lock:
            if self._session is not None and not self._session.closed:
                await self._session.close()
                self._session = None


def _is_ai_insight(envelope: Envelope, prefix: str = _DEFAULT_INSIGHT_PREFIX) -> bool:
    """Return True when the envelope is an AI-generated insight message."""
    if envelope.kind != MessageKind.CHAT:
        return False
    text: str = envelope.payload.get("text", "") if isinstance(envelope.payload, dict) else ""
    return text.startswith(prefix)


class InferenceResult(BaseModel):
    """Structured result from an AI inference pass."""

    summary: str
    raw_response: str


class NemotronClient:
    """Async client for the NVIDIA Nemotron NIM API.

    Pure retry/backoff/parse logic over an injectable :class:`HttpTransport`; the
    default transport is :class:`AiohttpTransport`. Inject ``transport`` (and/or
    ``sleep``) to test without sockets or to swap the HTTP backend.
    """

    def __init__(
        self,
        config: NemotronConfig,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        transport: HttpTransport | None = None,
    ) -> None:
        self.config = config
        self._sleep = sleep
        self._transport: HttpTransport = transport if transport is not None else AiohttpTransport()

    async def analyze(self, envelope: Envelope) -> InferenceResult:
        if not self.config.enabled or not self.config.api_key:
            return InferenceResult(summary="", raw_response="")

        prompt = (
            f"Analyze this {envelope.kind.value} message from {envelope.source_uid}: "
            f"{json.dumps(envelope.payload)}"
        )
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": self.config.system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self.config.base_url.rstrip('/')}/chat/completions"
        retries = self.config.max_retries

        for attempt in range(retries + 1):
            try:
                resp = await self._transport.post_json(
                    url, headers=headers, json_body=payload, timeout_s=self.config.timeout_s
                )
            except InferenceTransportError as exc:
                if attempt == retries:
                    _log.error("inference_error", error=str(exc), exc_info=True)
                    raise
                _log.debug("inference_transport_retry", attempt=attempt, error=str(exc))
                await self._sleep(self.config.backoff_base**attempt)
                continue

            if resp.status == _HTTP_TOO_MANY_REQUESTS and attempt < retries:
                _log.debug("inference_rate_limited", attempt=attempt)
                await self._sleep(self.config.backoff_base**attempt)
                continue
            if resp.status >= _HTTP_ERROR_FLOOR:
                if attempt < retries:
                    _log.debug("inference_http_retry", attempt=attempt, status=resp.status)
                    await self._sleep(self.config.backoff_base**attempt)
                    continue
                _log.error("inference_http_error", status=resp.status)
                raise InferenceHttpError(resp.status)

            data = resp.payload
            content: str = data["choices"][0]["message"]["content"]
            _log.debug("inference_success", reply_chars=len(content))
            return InferenceResult(summary=content, raw_response=json.dumps(data))

        raise InferenceError("inference failed after max retries")  # pragma: no cover

    async def close(self) -> None:
        """Close the underlying transport, if any."""
        await self._transport.aclose()


class InferenceService:
    """Subscribes to mesh traffic, runs inference, and broadcasts insights."""

    def __init__(
        self,
        config: NemotronConfig,
        router: Router,
        clock: Clock,
        id_factory: IdFactory,
        source_uid: str,
        *,
        transport: HttpTransport | None = None,
    ) -> None:
        self.config = config
        self.router = router
        self.clock = clock
        self.id_factory = id_factory
        self.source_uid = source_uid
        self.client = NemotronClient(config, transport=transport)
        self._bg_tasks: set[asyncio.Task[None]] = set()
        self._running = False
        self._subscribed = False

    def start(self) -> None:
        if not self.config.enabled or self._subscribed:
            return
        if not self.config.api_key:
            _log.warning("inference_service_missing_api_key")
            return
        self._subscribed = True
        self._running = True
        self.router.subscribe(self.handle_message)
        _log.info("inference_service_started", model=self.config.model)

    async def handle_message(self, envelope: Envelope) -> None:
        # Bail if the service has been stopped.
        if not self._running:
            return

        # Prevent infinite loops by not responding to our own inference messages.
        if envelope.source_uid == self.source_uid:
            return

        # Avoid analyzing existing AI insights to prevent multi-node feedback loops.
        if _is_ai_insight(envelope, self.config.insight_prefix):
            return

        task = asyncio.create_task(self._analyze_and_publish(envelope))
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    async def _analyze_and_publish(self, envelope: Envelope) -> None:
        try:
            result = await self.client.analyze(envelope)
            if not result.summary:
                return

            reply = Envelope(
                schema_version=SCHEMA_VERSION,
                msg_id=self.id_factory.new_id(),
                ts=self.clock.now(),
                source_uid=self.source_uid,
                kind=MessageKind.CHAT,
                payload=ChatPayload(
                    text=f"{self.config.insight_prefix} {result.summary}",
                    to=envelope.source_uid,
                ).model_dump(),
            )
            await self.router.publish(reply)
            _log.info("inference_published", original_id=envelope.msg_id, reply_id=reply.msg_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            _log.warning("inference_task_failed", exc_info=True)

    async def stop(self) -> None:
        self._running = False
        for t in list(self._bg_tasks):
            t.cancel()
        if self._bg_tasks:
            await asyncio.gather(*self._bg_tasks, return_exceptions=True)
        self._bg_tasks.clear()
        await self.client.close()
