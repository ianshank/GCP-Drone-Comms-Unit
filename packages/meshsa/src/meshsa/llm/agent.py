"""The situational-awareness agent: a read-only LLM over the SA tools.

``SAAgent`` runs a manual Anthropic tool-use loop (Claude Opus, adaptive
thinking). The loop is deliberately hand-rolled rather than using the SDK tool
runner so that (a) every tool call is dispatched through our read-only
``ToolDispatcher`` — the model can never issue a command — and (b) the loop is
fully unit-testable: the Messages API is injected behind the ``MessagesAPI``
protocol, so tests drive it with a scripted fake client and need neither a
network nor an API key.

Build a real agent with :func:`build_agent`, which lazy-imports ``anthropic``.
"""

from __future__ import annotations

import os
from typing import Any, Protocol, cast

from pydantic import BaseModel

from .sources import TelemetrySource, TrackSource
from .tools import ToolDispatcher, tool_specs

#: Default Claude model. Override per deployment with ``MESHSA_LLM_MODEL``.
DEFAULT_MODEL = "claude-opus-4-8"
DEFAULT_MAX_TOKENS = 2048
DEFAULT_MAX_ITERATIONS = 6

SYSTEM_PROMPT = (
    "You are a situational-awareness assistant embedded in a field drone "
    "comms unit. You bridge a MAVLink autopilot and a TAK/ATAK network. "
    "You are strictly READ-ONLY and advisory: you observe and report, you "
    "never issue flight commands, arm/disarm, change modes, or alter tracks. "
    "Use the provided tools to read live drone telemetry and TAK tracks rather "
    "than guessing or relying on prior values. Be concise and factual; report "
    "values with units. If telemetry is unavailable, say so plainly. For "
    "anything that would change vehicle or mission state, tell the operator to "
    "use the flight-control UI — that is not your role."
)


class _MessageLike(Protocol):
    stop_reason: str | None
    content: list[Any]


class MessagesAPI(Protocol):
    """Structural type for ``anthropic.AsyncAnthropic().messages``."""

    async def create(self, **kwargs: Any) -> _MessageLike: ...


class AgentReply(BaseModel):
    """Result of one ``SAAgent.ask`` turn."""

    text: str
    stop_reason: str
    tool_calls: list[str] = []


class SAAgent:
    """Read-only SA assistant driving an injected Anthropic Messages API."""

    def __init__(
        self,
        messages: MessagesAPI,
        dispatcher: ToolDispatcher,
        *,
        model: str = DEFAULT_MODEL,
        system: str = SYSTEM_PROMPT,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
    ) -> None:
        self._messages = messages
        self._dispatcher = dispatcher
        self._model = model
        self._system = system
        self._max_tokens = max_tokens
        self._max_iterations = max_iterations
        self._tools = tool_specs()

    async def ask(self, prompt: str, history: list[dict[str, Any]] | None = None) -> AgentReply:
        """Answer ``prompt``, running read-only tool calls until the model stops.

        ``history`` may carry prior turns (assistant content blocks are appended
        verbatim, preserving thinking-block signatures). Returns the final text
        plus the names of every tool invoked, for observability.
        """
        messages: list[Any] = list(history or [])
        messages.append({"role": "user", "content": prompt})
        tool_calls: list[str] = []

        for _ in range(self._max_iterations):
            response = await self._messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=self._system,
                tools=self._tools,
                messages=messages,
                thinking={"type": "adaptive"},
            )
            blocks = list(response.content)
            messages.append({"role": "assistant", "content": blocks})

            if response.stop_reason != "tool_use":
                return AgentReply(
                    text=_extract_text(blocks),
                    stop_reason=response.stop_reason or "end_turn",
                    tool_calls=tool_calls,
                )

            results: list[dict[str, Any]] = []
            for block in blocks:
                if getattr(block, "type", None) != "tool_use":
                    continue
                tool_calls.append(block.name)
                result = await self._dispatcher.dispatch(block.name, block.input)
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result.content,
                        "is_error": result.is_error,
                    }
                )
            messages.append({"role": "user", "content": results})

        return AgentReply(
            text="Reached the tool-call limit before finishing; please narrow the question.",
            stop_reason="max_iterations",
            tool_calls=tool_calls,
        )


def _extract_text(blocks: list[Any]) -> str:
    return "".join(b.text for b in blocks if getattr(b, "type", None) == "text").strip()


def build_agent(
    telemetry: TelemetrySource,
    tracks: TrackSource,
    *,
    api_key: str | None = None,
    model: str | None = None,
) -> SAAgent:  # pragma: no cover - constructs a real network client
    """Construct an ``SAAgent`` backed by a real ``anthropic.AsyncAnthropic``.

    ``anthropic`` is imported here so importing this module never requires the
    ``[llm]`` extra. The model defaults to ``MESHSA_LLM_MODEL`` then
    :data:`DEFAULT_MODEL`; the API key resolves from ``ANTHROPIC_API_KEY`` when
    not passed explicitly.
    """
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(api_key=api_key) if api_key else AsyncAnthropic()
    resolved_model = model or os.environ.get("MESHSA_LLM_MODEL", DEFAULT_MODEL)
    # The SDK's overloaded create() is narrower than our **kwargs protocol; the
    # call sites in ``ask`` use only the subset every overload accepts.
    messages = cast(MessagesAPI, client.messages)
    return SAAgent(messages, ToolDispatcher(telemetry, tracks), model=resolved_model)
