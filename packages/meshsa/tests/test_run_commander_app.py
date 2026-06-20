"""End-to-end tests for flightctl/run_commander.py's aiohttp app (real routes).

Drives ``build_app`` through an in-process aiohttp server with a fake CommandService,
exercising the auth gate, the CommandError->HTTP status mapping, bad-params handling,
and a stage->confirm happy path. aiohttp ships in [llm]/[health], not [dev], so this
is skipped on the per-PR CI (mirrors test_llm_server_app.py) and runs on nightly.
"""

from __future__ import annotations

import pytest

pytest.importorskip("aiohttp")

# run_commander lives in flightctl/, made importable via the pytest `pythonpath` option
# in pyproject.toml (no per-test sys.path mutation -> no cross-test leakage).
import run_commander  # noqa: E402
from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from meshsa.command import (  # noqa: E402
    ArmBlockedError,
    CommanderSettings,
    CommandNotAllowedError,
    CommandOutcome,
    ForceConfirmationRequired,
    StagedCommand,
    UnknownCommandError,
    build_command,
)

_SPEC = build_command("rtl", CommanderSettings())


class FakeService:
    """Configurable stand-in for CommandService (stage/confirm/cancel)."""

    def __init__(self, *, stage=None, confirm=None):
        self._stage = stage
        self._confirm = confirm
        self.cancelled: list[str] = []

    def stage(self, name, params=None):
        if isinstance(self._stage, Exception):
            raise self._stage
        if callable(self._stage):
            return self._stage(name, params)
        return StagedCommand("cid-1", name, 20, requires_force_confirm=False)

    def confirm(self, token, *, force_ack=False):
        if isinstance(self._confirm, Exception):
            raise self._confirm
        if callable(self._confirm):
            return self._confirm(token, force_ack)
        return CommandOutcome(_SPEC, accepted=True, result=0, attempts=1, reason="")

    def cancel(self, token):
        self.cancelled.append(token)


async def _client(service, token=None) -> TestClient:
    client = TestClient(TestServer(run_commander.build_app(service, token)))
    await client.start_server()
    return client


async def test_healthz_open() -> None:
    client = await _client(FakeService())
    try:
        resp = await client.get("/healthz")
        assert resp.status == 200
        assert (await resp.json())["status"] == "ok"
    finally:
        await client.close()


async def test_command_routes_require_token_when_set() -> None:
    client = await _client(FakeService(), token="s3cr3t")
    try:
        for route, body in (
            ("/command/stage", {"name": "rtl"}),
            ("/command/confirm", {"confirmation_id": "x"}),
            ("/command/cancel", {"confirmation_id": "x"}),
        ):
            resp = await client.post(route, json=body)  # no Authorization header
            assert resp.status == 401
    finally:
        await client.close()


async def test_stage_success_returns_confirmation_id() -> None:
    client = await _client(FakeService())
    try:
        resp = await client.post("/command/stage", json={"name": "rtl"})
        assert resp.status == 200
        body = await resp.json()
        assert body["confirmation_id"] == "cid-1"
        assert body["name"] == "rtl"
    finally:
        await client.close()


@pytest.mark.parametrize(
    "exc,status",
    [
        (CommandNotAllowedError("arm"), 403),
        (UnknownCommandError("nope"), 400),
        (TypeError("unexpected kwarg"), 400),  # bad params from build_command
        (ValueError("bad number"), 400),
    ],
)
async def test_stage_error_mapping(exc, status) -> None:
    client = await _client(FakeService(stage=exc))
    try:
        resp = await client.post("/command/stage", json={"name": "x", "params": {}})
        assert resp.status == status
    finally:
        await client.close()


async def test_stage_rejects_malformed_body() -> None:
    client = await _client(FakeService())
    try:
        r1 = await client.post("/command/stage", json={"params": {}})  # missing name
        assert r1.status == 400
        r2 = await client.post("/command/stage", data="not json")
        assert r2.status == 400
    finally:
        await client.close()


@pytest.mark.parametrize(
    "exc,status",
    [
        (ForceConfirmationRequired("force_disarm"), 409),
        (ArmBlockedError("no fresh health"), 409),
        (UnknownCommandError("gone"), 400),
    ],
)
async def test_confirm_error_mapping(exc, status) -> None:
    client = await _client(FakeService(confirm=exc))
    try:
        resp = await client.post("/command/confirm", json={"confirmation_id": "x"})
        assert resp.status == status
    finally:
        await client.close()


async def test_confirm_rejected_outcome_is_502() -> None:
    rejected = CommandOutcome(_SPEC, accepted=False, result=4, attempts=3, reason="terminal_reject")
    client = await _client(FakeService(confirm=lambda t, f: rejected))
    try:
        resp = await client.post("/command/confirm", json={"confirmation_id": "x"})
        assert resp.status == 502
        assert (await resp.json())["accepted"] is False
    finally:
        await client.close()


async def test_cancel_returns_ok() -> None:
    svc = FakeService()
    client = await _client(svc)
    try:
        resp = await client.post("/command/cancel", json={"confirmation_id": "cid-1"})
        assert resp.status == 200
        assert (await resp.json())["ok"] is True
        assert svc.cancelled == ["cid-1"]
    finally:
        await client.close()


async def test_stage_then_confirm_happy_path() -> None:
    # Cheap substitute for SITL-in-CI: the full stage->confirm wiring end to end.
    client = await _client(FakeService())
    try:
        staged = await (await client.post("/command/stage", json={"name": "rtl"})).json()
        resp = await client.post(
            "/command/confirm", json={"confirmation_id": staged["confirmation_id"]}
        )
        assert resp.status == 200
        body = await resp.json()
        assert body["accepted"] is True
        assert body["result"] == 0
    finally:
        await client.close()
