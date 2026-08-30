"""``NemotronClient``: pure retry/backoff/parse logic over an injectable transport.

Split out of the former flat ``inference.py`` (code-hygiene-modularity T-4.1b).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from pydantic import BaseModel

from ..models import Envelope
from .config import NemotronConfig
from .errors import (
    InferenceError,
    InferenceHttpError,
    InferenceTransportError,
    _is_transient_status,
)
from .transport import AiohttpTransport, HttpTransport

_log = structlog.get_logger("meshsa.inference")

#: First HTTP status considered an error response (4xx client errors).
_HTTP_ERROR_FLOOR = 400
#: OpenAI-compatible chat-completions path appended to ``NemotronConfig.base_url``.
_CHAT_COMPLETIONS_PATH = "/chat/completions"


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
