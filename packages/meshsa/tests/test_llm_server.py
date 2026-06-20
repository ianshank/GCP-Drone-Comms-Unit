"""Unit tests for the chat request handler and widget."""

from __future__ import annotations

from typing import Any

import pytest

from meshsa.llm.agent import AgentReply
from meshsa.llm.server import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    MAX_PROMPT_CHARS,
    authorize,
    chat_reply,
    is_loopback,
    resolve_config,
    validate_bind,
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


async def test_chat_reply_rejects_oversized_prompt_without_calling_model() -> None:
    agent = _FakeAgent(AgentReply(text="x", stop_reason="end_turn"))
    body, status = await chat_reply(agent, {"prompt": "A" * (MAX_PROMPT_CHARS + 1)})
    assert status == 400
    assert "too long" in body["error"]
    assert agent.prompts == []  # cost/latency DoS guard: model never invoked


async def test_chat_reply_accepts_prompt_at_limit() -> None:
    agent = _FakeAgent(AgentReply(text="ok", stop_reason="end_turn"))
    _body, status = await chat_reply(agent, {"prompt": "A" * MAX_PROMPT_CHARS})
    assert status == 200


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


def test_resolve_config_rejects_bad_or_out_of_range_port() -> None:
    with pytest.raises(ValueError, match="MESHSA_LLM_PORT: expected an integer"):
        resolve_config({"MESHSA_LLM_PORT": "notaport"})
    with pytest.raises(ValueError, match="above the maximum 65535"):
        resolve_config({"MESHSA_LLM_PORT": "70000"})


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


def test_default_host_is_loopback() -> None:
    # Regression guard: the assistant must not default to an exposed bind.
    assert DEFAULT_HOST == "127.0.0.1"
    assert is_loopback(DEFAULT_HOST)


def test_resolve_config_token_defaults_to_none_and_empty_is_none() -> None:
    assert resolve_config({}).token is None
    assert resolve_config({"MESHSA_LLM_TOKEN": ""}).token is None
    assert resolve_config({"MESHSA_LLM_TOKEN": "s3cr3t"}).token == "s3cr3t"


def test_authorize_open_when_no_token() -> None:
    # No token configured -> open (loopback is enforced by validate_bind instead).
    assert authorize(None, None) is True
    assert authorize(None, "anything") is True


def test_authorize_requires_matching_bearer_when_token_set() -> None:
    assert authorize("s3cr3t", "Bearer s3cr3t") is True
    assert authorize("s3cr3t", "bearer s3cr3t") is True  # scheme is case-insensitive
    assert authorize("s3cr3t", "Bearer wrong") is False
    assert authorize("s3cr3t", "s3cr3t") is False  # missing scheme
    assert authorize("s3cr3t", "Basic s3cr3t") is False  # wrong scheme
    assert authorize("s3cr3t", "Bearer ") is False
    assert authorize("s3cr3t", None) is False


def test_authorize_handles_non_ascii_without_raising() -> None:
    # hmac.compare_digest raises TypeError on non-ASCII str; authorize must
    # compare bytes so an odd/attacker-supplied bearer yields a clean False
    # (401), never an unhandled 500.
    assert authorize("s3cr3t", "Bearer café") is False  # non-ASCII presented
    assert authorize("pâssword", "Bearer pâssword") is True  # non-ASCII token matches
    assert authorize("pâssword", "Bearer password") is False


def test_authorize_strips_token_and_bearer_symmetrically() -> None:
    # A token sourced with a trailing newline (resolve_config strips it) still
    # matches a plain bearer — no permanent lockout from stray whitespace.
    assert resolve_config({"MESHSA_LLM_TOKEN": "s3cr3t\n"}).token == "s3cr3t"
    assert resolve_config({"MESHSA_LLM_TOKEN": "   "}).token is None
    assert authorize("s3cr3t", "Bearer s3cr3t\n") is True


def test_validate_bind_allows_loopback_without_token() -> None:
    validate_bind("127.0.0.1", None)  # no raise
    validate_bind("localhost", None)
    validate_bind("0.0.0.0", "s3cr3t")  # exposed but authenticated -> ok


def test_validate_bind_refuses_exposed_without_token() -> None:
    with pytest.raises(ValueError, match="MESHSA_LLM_TOKEN"):
        validate_bind("0.0.0.0", None)
