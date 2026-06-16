"""Integration tests for the SA-assistant aiohttp app (real routes via TestClient).

These drive ``build_app`` end-to-end through an in-process aiohttp server so the
actual request wiring — bearer-token gate on ``/chat``, the static widget, and
``/healthz`` — is exercised, not just the pure ``authorize``/``chat_reply`` units.
"""

from __future__ import annotations

from typing import Any

from aiohttp.test_utils import TestClient, TestServer

from meshsa.llm.agent import AgentReply
from meshsa.llm.server import build_app


class _FakeAgent:
    async def ask(self, prompt: str, history: list[dict[str, Any]] | None = None) -> AgentReply:
        return AgentReply(text="ok", stop_reason="end_turn", tool_calls=[])


async def _client(token: str | None) -> TestClient:
    client = TestClient(TestServer(build_app(_FakeAgent(), token)))
    await client.start_server()
    return client


async def test_index_and_healthz_are_open() -> None:
    client = await _client(token=None)
    try:
        idx = await client.get("/")
        assert idx.status == 200
        assert "SA Assistant" in await idx.text()
        hz = await client.get("/healthz")
        assert hz.status == 200
        assert (await hz.json())["status"] == "ok"
    finally:
        await client.close()


async def test_chat_open_when_no_token_configured() -> None:
    client = await _client(token=None)
    try:
        res = await client.post("/chat", json={"prompt": "hi"})
        assert res.status == 200
        assert (await res.json())["reply"] == "ok"
    finally:
        await client.close()


async def test_chat_rejects_without_and_with_wrong_bearer() -> None:
    client = await _client(token="s3cr3t")
    try:
        missing = await client.post("/chat", json={"prompt": "hi"})
        assert missing.status == 401
        assert (await missing.json())["error"] == "unauthorized"

        wrong = await client.post(
            "/chat", json={"prompt": "hi"}, headers={"Authorization": "Bearer nope"}
        )
        assert wrong.status == 401
    finally:
        await client.close()


async def test_chat_handles_malformed_json_body() -> None:
    client = await _client(token=None)
    try:
        # Non-JSON body -> request.json() raises -> payload None -> 400 from chat_reply.
        res = await client.post(
            "/chat", data="not json", headers={"Content-Type": "application/json"}
        )
        assert res.status == 400
    finally:
        await client.close()


async def test_chat_accepts_correct_bearer() -> None:
    client = await _client(token="s3cr3t")
    try:
        ok = await client.post(
            "/chat", json={"prompt": "hi"}, headers={"Authorization": "Bearer s3cr3t"}
        )
        assert ok.status == 200
        assert (await ok.json())["reply"] == "ok"
    finally:
        await client.close()
