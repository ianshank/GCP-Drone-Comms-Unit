"""Unit tests for the chat request handler and widget."""

from __future__ import annotations

from typing import Any

from meshsa.llm.agent import AgentReply
from meshsa.llm.server import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    chat_reply,
    resolve_config,
)
from meshsa.llm.sources import (
    DEFAULT_DRONE_UID,
    DEFAULT_FTS_TRACKS_URL,
    DEFAULT_MAVLINK2REST_URL,
)
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


async def test_chat_reply_agent_error_becomes_502_without_leaking_detail() -> None:
    agent = _FakeAgent(raises=RuntimeError("internal url https://secret:9/x"))
    body, status = await chat_reply(agent, {"prompt": "hi"})
    assert status == 502
    assert body["error"] == "assistant unavailable; check the server logs"
    assert "secret" not in body["error"]  # upstream detail logged, not returned


def test_resolve_config_defaults_when_env_empty() -> None:
    cfg = resolve_config({})
    assert cfg.host == DEFAULT_HOST
    assert cfg.port == DEFAULT_PORT
    assert cfg.mavlink2rest_url == DEFAULT_MAVLINK2REST_URL
    assert cfg.drone_uid == DEFAULT_DRONE_UID
    assert cfg.fts_tracks_url == DEFAULT_FTS_TRACKS_URL


def test_resolve_config_applies_env_overrides() -> None:
    cfg = resolve_config(
        {
            "MESHSA_LLM_HOST": "127.0.0.1",
            "MESHSA_LLM_PORT": "9999",
            "MESHSA_MAVLINK2REST_URL": "http://gw:8088",
            "MESHSA_DRONE_UID": "uav-42",
            "MESHSA_FTS_TRACKS_URL": "http://fts/tracks",
        }
    )
    assert cfg.host == "127.0.0.1"
    assert cfg.port == 9999  # parsed to int
    assert cfg.mavlink2rest_url == "http://gw:8088"
    assert cfg.drone_uid == "uav-42"
    assert cfg.fts_tracks_url == "http://fts/tracks"


def test_widget_html_is_self_contained() -> None:
    assert CHAT_WIDGET_HTML.startswith("<!doctype html>")
    assert 'fetch("chat"' in CHAT_WIDGET_HTML  # posts to same-origin /chat
    assert "SA Assistant" in CHAT_WIDGET_HTML
