"""Unit tests for the SAAgent tool-use loop, driven by a scripted fake client.

The fake ``messages`` object satisfies the ``MessagesAPI`` protocol structurally,
so the loop is exercised end to end without ``anthropic``, a network, or a key.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from meshsa.llm.agent import SAAgent, _extract_text
from meshsa.llm.sources import DroneState, StaticTelemetrySource, StaticTrackSource, Track
from meshsa.llm.tools import GET_DRONE_STATE, LIST_TRACKS, ToolDispatcher


@dataclass
class _TextBlock:
    text: str
    type: str = "text"


@dataclass
class _ToolUseBlock:
    name: str
    id: str
    input: dict[str, Any]
    type: str = "tool_use"


@dataclass
class _Response:
    content: list[Any]
    stop_reason: str


@dataclass
class _FakeMessages:
    """Returns queued responses; records every create() call for assertions."""

    responses: list[_Response]
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def create(self, **kwargs: Any) -> _Response:
        # Snapshot the messages list as the real SDK would serialize it at call
        # time — the agent mutates the same list in place across iterations.
        recorded = dict(kwargs)
        recorded["messages"] = list(kwargs["messages"])
        self.calls.append(recorded)
        return self.responses.pop(0)


def _dispatcher() -> ToolDispatcher:
    return ToolDispatcher(
        StaticTelemetrySource(DroneState(uid="uav-1", relative_alt_m=30.0)),
        StaticTrackSource([Track(uid="T1", callsign="ALPHA")]),
    )


async def test_direct_text_answer_no_tools() -> None:
    fake = _FakeMessages([_Response([_TextBlock("All nominal.")], "end_turn")])
    agent = SAAgent(fake, _dispatcher())
    reply = await agent.ask("status?")
    assert reply.text == "All nominal."
    assert reply.stop_reason == "end_turn"
    assert reply.tool_calls == []
    # First call carries the read-only tools and adaptive thinking.
    assert {t["name"] for t in fake.calls[0]["tools"]} == {GET_DRONE_STATE, LIST_TRACKS}
    assert fake.calls[0]["thinking"] == {"type": "adaptive"}


async def test_single_tool_call_then_answer() -> None:
    fake = _FakeMessages(
        [
            _Response([_ToolUseBlock(GET_DRONE_STATE, "tu_1", {})], "tool_use"),
            _Response([_TextBlock("Altitude is 30.0 m.")], "end_turn"),
        ]
    )
    agent = SAAgent(fake, _dispatcher())
    reply = await agent.ask("how high?")
    assert reply.tool_calls == [GET_DRONE_STATE]
    assert reply.text == "Altitude is 30.0 m."
    # Second create() must include the tool_result the loop fed back.
    second_msgs = fake.calls[1]["messages"]
    tool_result_turn = second_msgs[-1]
    assert tool_result_turn["role"] == "user"
    block = tool_result_turn["content"][0]
    assert block["type"] == "tool_result"
    assert block["tool_use_id"] == "tu_1"
    assert "uav-1" in block["content"]
    assert block["is_error"] is False


async def test_multiple_tool_calls_in_one_turn() -> None:
    fake = _FakeMessages(
        [
            _Response(
                [
                    _ToolUseBlock(GET_DRONE_STATE, "tu_1", {}),
                    _ToolUseBlock(LIST_TRACKS, "tu_2", {}),
                ],
                "tool_use",
            ),
            _Response([_TextBlock("done")], "end_turn"),
        ]
    )
    agent = SAAgent(fake, _dispatcher())
    reply = await agent.ask("full picture?")
    assert reply.tool_calls == [GET_DRONE_STATE, LIST_TRACKS]
    results = fake.calls[1]["messages"][-1]["content"]
    assert [r["tool_use_id"] for r in results] == ["tu_1", "tu_2"]


async def test_text_blocks_alongside_tool_use_are_ignored_until_final() -> None:
    fake = _FakeMessages(
        [
            _Response(
                [_TextBlock("let me check"), _ToolUseBlock(GET_DRONE_STATE, "tu_1", {})],
                "tool_use",
            ),
            _Response([_TextBlock("30 m")], "end_turn"),
        ]
    )
    reply = await SAAgent(fake, _dispatcher()).ask("alt?")
    assert reply.text == "30 m"


async def test_history_is_prepended() -> None:
    fake = _FakeMessages([_Response([_TextBlock("hi")], "end_turn")])
    agent = SAAgent(fake, _dispatcher())
    history = [{"role": "user", "content": "earlier"}]
    await agent.ask("now", history=history)
    sent = fake.calls[0]["messages"]
    assert sent[0] == {"role": "user", "content": "earlier"}
    assert sent[1] == {"role": "user", "content": "now"}
    assert history == [{"role": "user", "content": "earlier"}]  # caller's list untouched


async def test_max_iterations_guard() -> None:
    # Always asks for a tool -> never terminates on its own.
    fake = _FakeMessages([_Response([_ToolUseBlock(LIST_TRACKS, "x", {})], "tool_use")] * 3)
    agent = SAAgent(fake, _dispatcher(), max_iterations=3)
    reply = await agent.ask("loop forever")
    assert reply.stop_reason == "max_iterations"
    assert "tool-call limit" in reply.text
    assert len(fake.calls) == 3


async def test_none_stop_reason_defaults_to_end_turn() -> None:
    fake = _FakeMessages([_Response([_TextBlock("x")], None)])  # type: ignore[arg-type]
    reply = await SAAgent(fake, _dispatcher()).ask("q")
    assert reply.stop_reason == "end_turn"


def test_extract_text_joins_and_strips() -> None:
    blocks = [_TextBlock("  a"), _ToolUseBlock("t", "i", {}), _TextBlock("b  ")]
    assert _extract_text(blocks) == "ab"


@pytest.mark.anyio
async def test_build_agent_resolves_env_vars() -> None:
    import sys
    from unittest.mock import MagicMock, patch

    mock_anthropic = MagicMock()
    orig_anthropic = sys.modules.get("anthropic")
    sys.modules["anthropic"] = mock_anthropic

    try:
        from meshsa.llm.agent import build_agent
        from meshsa.llm.sources import StaticTelemetrySource, StaticTrackSource

        mock_async_anthropic = mock_anthropic.AsyncAnthropic
        mock_client = MagicMock()
        mock_async_anthropic.return_value = mock_client

        # 1. Test defaults
        with patch.dict("os.environ", {}, clear=True):
            agent = build_agent(
                StaticTelemetrySource(None),
                StaticTrackSource([]),
            )
            assert agent._model == "claude-opus-4-8"
            assert agent._max_tokens == 2048
            assert agent._max_iterations == 6

        # 2. Test overrides
        env = {
            "MESHSA_LLM_MODEL": "claude-custom",
            "MESHSA_LLM_MAX_TOKENS": "1000",
            "MESHSA_LLM_MAX_ITERATIONS": "5",
        }
        with patch.dict("os.environ", env, clear=True):
            agent2 = build_agent(
                StaticTelemetrySource(None),
                StaticTrackSource([]),
            )
            assert agent2._model == "claude-custom"
            assert agent2._max_tokens == 1000
            assert agent2._max_iterations == 5
    finally:
        if orig_anthropic is None:
            sys.modules.pop("anthropic", None)
        else:
            sys.modules["anthropic"] = orig_anthropic
