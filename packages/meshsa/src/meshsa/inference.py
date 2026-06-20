"""Nemotron Ultra Inference Layer.

Provides AI-driven analysis of situational-awareness messages by bridging
the mesh network to NVIDIA's OpenAI-compatible NIM API using aiohttp.
"""

from __future__ import annotations

import asyncio
import json

import aiohttp
import structlog
from pydantic import BaseModel

from .config import NemotronConfig
from .models import ChatPayload, Envelope, MessageKind
from .protocols import Clock, IdFactory
from .router import Router
from .version import SCHEMA_VERSION

_log = structlog.get_logger("meshsa.inference")


class InferenceResult(BaseModel):
    """Structured result from an AI inference pass."""

    summary: str
    raw_response: str


class NemotronClient:
    """Async client for the NVIDIA Nemotron NIM API."""

    def __init__(self, config: NemotronConfig) -> None:
        self.config = config

    async def analyze(self, envelope: Envelope) -> InferenceResult:
        if not self.config.enabled or not self.config.api_key:
            return InferenceResult(
                summary="", raw_response=""
            )

        prompt = (
            f"Analyze this {envelope.kind.value} message from {envelope.source_uid}: "
            f"{json.dumps(envelope.payload)}"
        )
        
        payload = {
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

        retries = self.config.max_retries
        for attempt in range(retries + 1):
            try:
                async with aiohttp.ClientSession() as session, session.post(
                    f"{self.config.base_url.rstrip('/')}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=self.config.timeout_s,
                ) as resp:
                    if resp.status == 429 and attempt < retries:
                        await asyncio.sleep(2 ** attempt)
                        continue
                    resp.raise_for_status()
                    data = await resp.json()
                    content = data["choices"][0]["message"]["content"]
                    return InferenceResult(
                        summary=content,
                        raw_response=content,
                    )
            except asyncio.TimeoutError:
                if attempt == retries:
                    _log.error("inference_timeout")
                    raise
            except aiohttp.ClientError as exc:
                if attempt == retries:
                    _log.error("inference_error", error=str(exc))
                    raise
            await asyncio.sleep(2 ** attempt)
            
        raise RuntimeError("Inference failed after max retries")


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

    def start(self) -> None:
        if not self.config.enabled:
            return
        self.router.subscribe(self.handle_message)
        _log.info("inference_service_started", model=self.config.model)

    async def handle_message(self, envelope: Envelope) -> None:
        # Prevent infinite loops by not responding to our own inference messages
        if envelope.source_uid == self.source_uid:
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
                    text=f"[AI Insight] {result.summary}",
                    to=envelope.source_uid,
                ).model_dump(),
            )
            await self.router.publish(reply)
            _log.info("inference_published", original_id=envelope.msg_id, reply_id=reply.msg_id)
        except Exception as exc:
            _log.warning("inference_task_failed", error=str(exc))

    async def stop(self) -> None:
        for t in list(self._bg_tasks):
            t.cancel()
        if self._bg_tasks:
            await asyncio.gather(*self._bg_tasks, return_exceptions=True)
        self._bg_tasks.clear()
