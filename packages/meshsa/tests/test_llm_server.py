"""Unit tests for the chat request handler and widget."""

from __future__ import annotations

from typing import Any

from meshsa.llm.agent import AgentReply
from meshsa.llm.server import chat_reply
from meshsa.llm.widget import CHAT_WIDGET_HTML


class _FakeAgent:
    def __init__(self, reply: AgentReply | None = None, raises: Exception | None = None) -> None:
        self._reply = reply
        self._raises = raises
        self.prompts: list[str] = []

    async def ask(self, prompt: str, history: list[dict[str, Any]] | None = None) -> AgentReply:
        self.prompts.append(prompt)
        if self._raises is not None:
            raise self._raises
        assert self._reply is not None
        return self._reply


async def test_chat_reply_happy_path() -> None:
    agent = _FakeAgent(
        AgentReply(text="30 m", stop_reason="end_turn", tool_calls=["get_drone_state"])
    )
    body, status = await chat_reply(agent, {"prompt": "  how high?  "})
    assert status == 200
    assert body["reply"] == "30 m"
    assert body["tools"] == ["get_drone_state"]
    assert body["stop_reason"] == "end_turn"
    assert agent.prompts == ["how high?"]  # trimmed before dispatch


async def test_chat_reply_missing_prompt() -> None:
    agent = _FakeAgent(AgentReply(text="x", stop_reason="end_turn"))
    for payload in ({}, {"prompt": ""}, {"prompt": "   "}, {"prompt": 5}):
        body, status = await chat_reply(agent, payload)
        assert status == 400
        assert "prompt" in body["error"]
    assert agent.prompts == []  # never dispatched


async def test_chat_reply_non_object_payload() -> None:
    agent = _FakeAgent(AgentReply(text="x", stop_reason="end_turn"))
    body, status = await chat_reply(agent, ["not", "a", "dict"])
    assert status == 400
    assert "JSON object" in body["error"]


async def test_chat_reply_agent_error_becomes_502() -> None:
    agent = _FakeAgent(raises=RuntimeError("model down"))
    body, status = await chat_reply(agent, {"prompt": "hi"})
    assert status == 502
    assert "model down" in body["error"]


def test_widget_html_is_self_contained() -> None:
    assert CHAT_WIDGET_HTML.startswith("<!doctype html>")
    assert 'fetch("chat"' in CHAT_WIDGET_HTML  # posts to same-origin /chat
    assert "SA Assistant" in CHAT_WIDGET_HTML
