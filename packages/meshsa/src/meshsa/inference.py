"""Nemotron Ultra Inference Layer.

Provides AI-driven analysis of situational-awareness messages by bridging
the mesh network to NVIDIA's OpenAI-compatible NIM API using aiohttp.

``aiohttp`` is an *optional* dependency — install ``meshsa[inference]``
to enable this module.  The package and ``build_node()`` import it
unconditionally but guard all runtime paths behind availability checks.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from pydantic import BaseModel

from .config import NemotronConfig
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


def _is_ai_insight(envelope: Envelope, prefix: str = _DEFAULT_INSIGHT_PREFIX) -> bool:
    """Return True when the envelope is an AI-generated insight message."""
    if envelope.kind != MessageKind.CHAT:
        return False
    text: str = envelope.payload.get("text", "") if isinstance(envelope.payload, dict) else ""
    return text.startswith(prefix)


def _require_aiohttp() -> None:
    """Raise with an actionable message when aiohttp is absent."""
    if aiohttp is None:
        raise RuntimeError(  # pragma: no cover — only when aiohttp absent
            "Nemotron inference requires aiohttp; install 'meshsa[inference]'"
        )


class InferenceResult(BaseModel):
    """Structured result from an AI inference pass."""

    summary: str
    raw_response: str


class NemotronClient:
    """Async client for the NVIDIA Nemotron NIM API."""

    def __init__(
        self,
        config: NemotronConfig,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.config = config
        self._sleep = sleep
        self._session: aiohttp.ClientSession | None = None
        self._session_lock: asyncio.Lock | None = None

    async def analyze(self, envelope: Envelope) -> InferenceResult:
        if not self.config.enabled or not self.config.api_key:
            return InferenceResult(summary="", raw_response="")

        _require_aiohttp()

        prompt = (
            f"Analyze this {envelope.kind.value} message from {envelope.source_uid}: "
            f"{json.dumps(envelope.payload)}"
        )

        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": [
                {
                    "role": "system",
                    "content": self.config.system_prompt,
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }

        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }

        timeout = aiohttp.ClientTimeout(total=self.config.timeout_s)
        retries = self.config.max_retries
        for attempt in range(retries + 1):
            try:
                if self._session_lock is None:
                    self._session_lock = asyncio.Lock()
                async with self._session_lock:
                    if self._session is None or self._session.closed:
                        self._session = aiohttp.ClientSession(timeout=timeout)
                    session = self._session
                async with session.post(
                    f"{self.config.base_url.rstrip('/')}/chat/completions",
                    headers=headers,
                    json=payload,
                ) as resp:
                    if resp.status == 429 and attempt < retries:
                        await self._sleep(self.config.backoff_base**attempt)
                        continue
                    resp.raise_for_status()
                    data = await resp.json()
                    content: str = data["choices"][0]["message"]["content"]
                    return InferenceResult(
                        summary=content,
                        raw_response=json.dumps(data),
                    )
            except asyncio.TimeoutError:
                if attempt == retries:
                    _log.error("inference_timeout")
                    raise
            except aiohttp.ClientError as exc:
                if attempt == retries:
                    _log.error("inference_error", error=str(exc))
                    raise
            await self._sleep(self.config.backoff_base**attempt)

        raise RuntimeError("Inference failed after max retries")  # pragma: no cover

    async def close(self) -> None:
        """Close the underlying HTTP session, if open."""
        if self._session_lock is None:
            self._session_lock = asyncio.Lock()
        async with self._session_lock:
            if self._session is not None and not self._session.closed:
                await self._session.close()
                self._session = None


class InferenceService:
    """Subscribes to mesh traffic, runs inference, and broadcasts insights."""

    def __init__(
        self,
        config: NemotronConfig,
        router: Router,
        clock: Clock,
        id_factory: IdFactory,
        source_uid: str,
    ) -> None:
        self.config = config
        self.router = router
        self.clock = clock
        self.id_factory = id_factory
        self.source_uid = source_uid
        self.client = NemotronClient(config)
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
