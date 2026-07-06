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
from collections import deque
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
#: First HTTP status considered an error response (4xx client errors).
_HTTP_ERROR_FLOOR = 400
#: First HTTP status considered a (retryable) server error (5xx).
_HTTP_SERVER_ERROR_FLOOR = 500
#: OpenAI-compatible chat-completions path appended to ``NemotronConfig.base_url``.
_CHAT_COMPLETIONS_PATH = "/chat/completions"


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


def _is_transient_status(status: int) -> bool:
    """True for HTTP statuses worth retrying/queueing: rate-limit (429) or 5xx server errors."""
    return status == _HTTP_TOO_MANY_REQUESTS or status >= _HTTP_SERVER_ERROR_FLOOR


def _is_offline_retryable(exc: InferenceError) -> bool:
    """True when a failure is a connectivity/transient condition worth an offline replay.

    Transport errors (API unreachable) and *transient* HTTP failures (429 / 5xx that already
    exhausted the retry budget) are offline-worthy. A permanent client error (401/400/404) or a
    malformed-payload / max-retries base ``InferenceError`` is **not** — replaying it can never
    succeed, so it must surface fast instead of cycling in the queue forever.
    """
    if isinstance(exc, InferenceTransportError):
        return True
    if isinstance(exc, InferenceHttpError):
        return _is_transient_status(exc.status)
    return False


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
        # Parse the structured-output schema once. NemotronConfig has already validated it as a
        # JSON object at config load (fail-fast there), so this cannot raise. None when unset.
        self._guided_json: Any | None = (
            json.loads(config.guided_json_schema) if config.guided_json_schema else None
        )

    @property
    def _want_json(self) -> bool:
        """True when a structured (JSON) reply was requested via either mechanism."""
        return self._guided_json is not None or self.config.response_format == "json"

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
        # Structured-output directive (spec §5). NVIDIA recommends its ``nvext.guided_json``
        # schema over the portable ``response_format`` JSON toggle (which allows any valid
        # JSON, including ``{}``), so the schema wins when both are set.
        if self._guided_json is not None:
            payload["nvext"] = {"guided_json": self._guided_json}
        elif self.config.response_format == "json":
            payload["response_format"] = {"type": "json_object"}
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self.config.base_url.rstrip('/')}{_CHAT_COMPLETIONS_PATH}"
        retries = self.config.max_retries

        # Every iteration returns or raises; the loop never falls through (the
        # final raise below is defensive) — tell coverage not to expect that edge.
        for attempt in range(retries + 1):  # pragma: no branch
            try:
                resp = await self._transport.post_json(
                    url, headers=headers, json_body=payload, timeout_s=self.config.timeout_s
                )
            except InferenceTransportError as exc:
                if attempt == retries:
                    _log.error("inference_error", error=str(exc), exc_info=True)
                    raise
                _log.debug("inference_transport_retry", attempt=attempt, error=str(exc))
                await self._sleep(self._backoff_delay(attempt))
                continue

            status = resp.status
            # Rate limiting and 5xx server errors are transient: retry with backoff.
            if _is_transient_status(status):
                if attempt < retries:
                    _log.debug("inference_http_retry", attempt=attempt, status=status)
                    await self._sleep(self._backoff_delay(attempt))
                    continue
                _log.error("inference_http_error", status=status, transient=True)
                raise InferenceHttpError(status)
            # Other 4xx (bad key, bad request) are not transient: fail fast.
            if status >= _HTTP_ERROR_FLOOR:
                _log.error("inference_http_error", status=status, transient=False)
                raise InferenceHttpError(status)

            return self._parse(
                resp.payload,
                want_json=self._want_json,
                summary_field=self.config.guided_json_summary_field,
            )

        raise InferenceError("inference failed after max retries")  # pragma: no cover

    def _backoff_delay(self, attempt: int) -> float:
        """Exponential backoff for ``attempt``, capped at ``backoff_max_s``."""
        return min(self.config.backoff_base**attempt, self.config.backoff_max_s)

    @staticmethod
    def _parse(
        data: dict[str, Any], *, want_json: bool = False, summary_field: str = "summary"
    ) -> InferenceResult:
        """Extract the completion text, mapping a malformed body to InferenceError.

        In structured (``want_json``) mode, a JSON-object reply carrying a string
        ``summary_field`` (config-driven, default ``"summary"``) is unwrapped to that field;
        any non-JSON or unshaped reply falls back to the raw text — logged as
        ``structured_parse_fallback`` so the missed structured contract is observable — so a
        structured request never loses the answer.
        """
        try:
            content: str = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise InferenceError("malformed completion payload") from exc
        summary = content
        if want_json:
            try:
                obj: Any = json.loads(content)
            except (json.JSONDecodeError, TypeError):
                obj = None
            if isinstance(obj, dict) and isinstance(obj.get(summary_field), str):
                summary = obj[summary_field]
            else:
                _log.debug("structured_parse_fallback", summary_field=summary_field)
        _log.debug("inference_success", reply_chars=len(summary))
        return InferenceResult(summary=summary, raw_response=json.dumps(data))

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
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.config = config
        self.router = router
        self.clock = clock
        self.id_factory = id_factory
        self.source_uid = source_uid
        self.client = NemotronClient(config, transport=transport, sleep=sleep)
        self._sleep = sleep
        self._bg_tasks: set[asyncio.Task[None]] = set()
        self._running = False
        self._subscribed = False
        # ── Rate limiting (spec §5). A BoundedSemaphore caps *concurrency*; the
        #    min-interval gate caps *rate* — a semaphore alone cannot. Both are no-ops
        #    at their defaults (0), preserving prior behavior. ──
        self._semaphore: asyncio.BoundedSemaphore | None = (
            asyncio.BoundedSemaphore(config.max_concurrent_requests)
            if config.max_concurrent_requests > 0
            else None
        )
        self._interval_lock = asyncio.Lock()
        self._last_request_at: float | None = None
        # ── Offline fallback (spec §5): a bounded queue of envelopes that failed while
        #    the API was unreachable, replayed on the next success. None = disabled. ──
        self._offline: deque[Envelope] | None = (
            deque(maxlen=config.offline_queue_max) if config.offline_queue_max > 0 else None
        )
        self._offline_dropped = 0
        self._drain_lock = asyncio.Lock()

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
            result = await self._gated_analyze(envelope)
            if not result.summary:
                return
            await self._publish(envelope, result)
            # Drain OUTSIDE any semaphore permit (`_gated_analyze` already released it) so a
            # backlog flush doesn't monopolize the concurrency cap.
            await self._drain_offline()
        except asyncio.CancelledError:
            raise
        except InferenceError as exc:
            # A connectivity/transient failure is queued for later replay (when a queue is
            # configured); a permanent one (bad key, malformed body) surfaces as before so it
            # fails fast and loud instead of cycling in the queue forever.
            if self._offline is not None and _is_offline_retryable(exc):
                self._offline_put(self._offline, envelope, front=False)
                _log.warning(
                    "inference_offline_enqueue", original_id=envelope.msg_id, error=str(exc)
                )
            else:
                _log.warning("inference_task_failed", exc_info=True)
        except Exception:
            _log.warning("inference_task_failed", exc_info=True)

    async def _gated_analyze(self, envelope: Envelope) -> InferenceResult:
        """Run one analysis through the rate-limit gate: space, then a per-call permit.

        Spacing happens *before* acquiring a permit (so a permit is never spent merely
        waiting), and the permit wraps only the network call — so both live requests and each
        offline replay honor ``min_interval_s`` and ``max_concurrent_requests`` identically.
        """
        await self._space()
        if self._semaphore is None:
            return await self.client.analyze(envelope)
        async with self._semaphore:
            return await self.client.analyze(envelope)

    async def _space(self) -> None:
        """Enforce ``min_interval_s`` spacing between requests via the injected clock."""
        if self.config.min_interval_s <= 0:
            return
        async with self._interval_lock:
            now = self.clock.now()
            if self._last_request_at is not None:
                wait = self.config.min_interval_s - (now - self._last_request_at)
                if wait > 0:
                    await self._sleep(wait)
            self._last_request_at = self.clock.now()

    async def _publish(self, envelope: Envelope, result: InferenceResult) -> None:
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

    def _offline_put(self, queue: deque[Envelope], envelope: Envelope, *, front: bool) -> None:
        """Add an envelope to the offline queue at either end, counting any overflow.

        ``front=True`` (a re-queued replay) preserves FIFO — the item returns to where it was
        popped. A full deque silently drops the item at the opposite end on insert, so we
        count it (drop-and-count, mirroring ``FlightLogger``) rather than lose it silently —
        this also covers the case where a concurrent producer refilled the queue during a
        drain ``await``.
        """
        if len(queue) == queue.maxlen:
            self._offline_dropped += 1
            _log.warning("inference_offline_dropped", dropped_total=self._offline_dropped)
        if front:
            queue.appendleft(envelope)
        else:
            queue.append(envelope)

    async def _drain_offline(self) -> None:
        """Replay queued envelopes after a success.

        A *transient* replay failure returns the item to the FRONT (FIFO) and stops draining —
        connectivity is likely down again. A *permanent* replay failure drops the item (counted)
        and continues, so one poison envelope can never block replay of the rest.
        """
        if not self._offline:
            return
        async with self._drain_lock:
            while self._offline:
                pending = self._offline.popleft()
                try:
                    result = await self._gated_analyze(pending)
                except InferenceError as exc:
                    if _is_offline_retryable(exc):
                        self._offline_put(self._offline, pending, front=True)
                        _log.warning("inference_offline_replay_failed", error=str(exc))
                        return
                    self._offline_dropped += 1
                    _log.warning(
                        "inference_offline_replay_dropped",
                        dropped_total=self._offline_dropped,
                        error=str(exc),
                    )
                    continue
                if result.summary:
                    await self._publish(pending, result)

    async def stop(self) -> None:
        self._running = False
        for t in list(self._bg_tasks):
            t.cancel()
        if self._bg_tasks:
            await asyncio.gather(*self._bg_tasks, return_exceptions=True)
        self._bg_tasks.clear()
        await self.client.close()
