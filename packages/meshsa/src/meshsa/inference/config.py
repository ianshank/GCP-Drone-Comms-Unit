"""``NemotronConfig`` — Nemotron inference tunables (``meshsa.inference``).

Relocated from the top-level ``meshsa.config`` (code-hygiene-modularity T-4.1b),
finishing the pattern ``UIConfig``/``ui/config.py`` already established:
each subsystem's config lives beside the code it configures.
``meshsa.config`` re-exports this class so every existing import path keeps
resolving.
"""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from ..defaults import DEFAULT_INFERENCE_BACKOFF_BASE, DEFAULT_INFERENCE_BACKOFF_MAX_S


class NemotronConfig(BaseModel):
    enabled: bool = False
    api_key: str = ""
    base_url: str = "https://integrate.api.nvidia.com/v1"
    model: str = "nvidia/nemotron-3-ultra-550b-a55b"
    system_prompt: str = "You are a tactical AI assistant. Summarize the user's message clearly. Keep it under 100 words."
    temperature: float = 0.6
    max_tokens: int = 512
    timeout_s: float = 30.0
    max_retries: int = 3
    backoff_base: float = Field(default=DEFAULT_INFERENCE_BACKOFF_BASE, ge=1.0)
    backoff_max_s: float = Field(default=DEFAULT_INFERENCE_BACKOFF_MAX_S, ge=0.0)
    insight_prefix: str = Field(default="[AI Insight]", min_length=1)
    # ── Track-B hardening (spec §5). Every field defaults to the prior behavior:
    #    0 / "" / "text" / () are all no-ops, so an existing deployment is unchanged. ──
    #: Minimum spacing between analysis requests (rate limiting); 0.0 = unspaced.
    min_interval_s: float = Field(default=0.0, ge=0.0)
    #: Max concurrent in-flight analysis requests (rate limiting); 0 = unbounded.
    max_concurrent_requests: int = Field(default=0, ge=0)
    #: Request the model return JSON. ``guided_json_schema`` (NVIDIA's ``nvext``,
    #: preferred) takes precedence; ``"json"`` sends the portable OpenAI
    #: ``response_format`` toggle; ``"text"`` is the default free-form reply.
    response_format: Literal["text", "json"] = "text"
    #: A JSON-schema string for NVIDIA's ``nvext.guided_json`` structured output;
    #: "" disables it (see spec §5 — NVIDIA recommends this over ``response_format``).
    #: Validated at config load: when set it must parse to a JSON object.
    guided_json_schema: str = ""
    #: Reply field unwrapped from a structured (JSON) response into the insight summary;
    #: match this to the key your ``guided_json_schema`` defines. Default ``"summary"``.
    guided_json_summary_field: str = Field(default="summary", min_length=1)
    #: Optional model allow-list; empty = no restriction. When set, ``model`` must be
    #: a member and :meth:`with_model` rejects anything outside it.
    models: tuple[str, ...] = ()
    #: Bounded offline queue depth for envelopes that failed while the API was
    #: unreachable; 0 = disabled (no queueing, prior behavior).
    offline_queue_max: int = Field(default=0, ge=0)
    #: Max in-flight background analysis tasks; 0 = unbounded (prior behaviour). A burst of
    #: inbound envelopes past this cap is shed (drop-and-count) rather than spawning unbounded
    #: tasks on a constrained edge node.
    max_pending_tasks: int = Field(default=0, ge=0)

    def _reject_model_not_allowed(self, model: str) -> None:
        """Raise when ``model`` is outside a configured allow-list (no-op if unset)."""
        if self.models and model not in self.models:
            raise ValueError(f"model {model!r} not in allow-list {self.models}")

    @model_validator(mode="after")
    def _validate_after(self) -> NemotronConfig:
        """Fail fast at config load: enforce the allow-list and parse the guided schema."""
        self._reject_model_not_allowed(self.model)
        if self.guided_json_schema:
            try:
                schema = json.loads(self.guided_json_schema)
            except json.JSONDecodeError as exc:
                raise ValueError(f"guided_json_schema is not valid JSON: {exc}") from exc
            if not isinstance(schema, dict):
                raise ValueError("guided_json_schema must be a JSON object")
        return self

    def with_model(self, model: str) -> NemotronConfig:
        """Return a copy pinned to ``model`` (multi-model switch).

        Rejects a model outside ``models`` when an allow-list is configured, so a runtime
        switch can never escape the operator-approved set. The manual re-check is required
        because Pydantic v2's ``model_copy`` does **not** re-run validators.
        """
        self._reject_model_not_allowed(model)
        return self.model_copy(update={"model": model})
