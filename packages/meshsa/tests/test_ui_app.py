"""Tests for meshsa.ui.app + sources + cli wiring — auth, routes, degradation (spec §7)."""

from __future__ import annotations

import json
from typing import Any

import pytest
import structlog
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from meshsa.ui.app import (
    UPSTREAM_ERROR,
    authorize,
    build_ui_app,
    guard,
    is_loopback,
    panel_manifest,
    validate_bind,
)
from meshsa.ui.cli import build_sources
from meshsa.ui.config import UIConfig
from meshsa.ui.logring import LogRing
from meshsa.ui.snapshot import SnapshotStore
from meshsa.ui.sources import AgentChatBackend, FpvLinkSource, NodeHealthSource, UISources

# ── fakes (no hardware, no radios, no sockets beyond aiohttp's test server) ──


class FakeSnapshot:
    def __init__(self, *, raise_on_read: bool = False) -> None:
        self.raise_on_read = raise_on_read

    def _fc(self, name: str) -> dict[str, Any]:
        if self.raise_on_read:
            raise RuntimeError("internal detail: sqlite:///secret/path")
        return {"type": "FeatureCollection", "features": [], "name": name}

    def tracks_geojson(self) -> dict[str, Any]:
        return self._fc("tracks")

    def detections_geojson(self) -> dict[str, Any]:
        return self._fc("detections")

    def counters(self) -> dict[str, int]:
        if self.raise_on_read:
            raise RuntimeError("internal detail: sqlite:///secret/path")
        return {"tracks_live": 0}


class FakeHealth:
    def snapshot(self) -> dict[str, Any]:
        return {"health": {"status": "ok"}, "metrics": {"rx": 1}}


class FakeFpv:
    def __init__(self, *, boom: bool = False) -> None:
        self.boom = boom

    def report(self) -> dict[str, Any]:
        if self.boom:
            raise RuntimeError("serial port /dev/ttyUSB0 vanished")
        return {"state": "healthy"}


class FakeChat:
    async def reply(self, payload: Any) -> tuple[dict[str, Any], int]:
        if not isinstance(payload, dict) or "prompt" not in payload:
            return {"error": "missing 'prompt'"}, 400
        return {"reply": f"echo: {payload['prompt']}"}, 200


class RaisingChat:
    async def reply(self, payload: Any) -> tuple[dict[str, Any], int]:
        raise RuntimeError("api key sk-secret leaked in exception text")


class FakeLogs:
    def entries(self) -> list[dict[str, Any]]:
        return [{"ts": 1.0, "level": "info", "event": "boot"}]


class RaisingLogs:
    def entries(self) -> list[dict[str, Any]]:
        raise RuntimeError("ring backing store corrupted")


def _sources(**overrides: Any) -> UISources:
    kwargs: dict[str, Any] = {
        "snapshot": FakeSnapshot(),
        "health": FakeHealth(),
        "fpv": FakeFpv(),
        "chat": FakeChat(),
        "logs": FakeLogs(),
    }
    kwargs.update(overrides)
    return UISources(**kwargs)


async def _client(app: web.Application) -> TestClient:
    client = TestClient(TestServer(app))
    await client.start_server()
    return client


# ── pure helpers ──────────────────────────────────────────────────────────────


def test_validate_bind_fail_closed() -> None:
    validate_bind("127.0.0.1", None)  # loopback needs no credential
    validate_bind("0.0.0.0", "token")
    with pytest.raises(ValueError) as excinfo:
        validate_bind("0.0.0.0", None)
    message = str(excinfo.value)
    assert "meshsa-ui" in message and "MESHSA_UI_TOKEN" in message


def test_build_app_construction_fails_closed() -> None:
    with pytest.raises(ValueError):
        build_ui_app(_sources(), UIConfig(), host="0.0.0.0")
    # An empty config token is no token (normalised at load): still refused.
    with pytest.raises(ValueError):
        build_ui_app(_sources(), UIConfig(token="   "), host="0.0.0.0")
    # Explicit token param overrides config.
    build_ui_app(_sources(), UIConfig(), host="0.0.0.0", token="t")


def test_guard_pure() -> None:
    assert guard(None, None) is None
    assert guard("t", "Bearer t") is None
    body, status = guard("t", "Bearer wrong")  # type: ignore[misc]
    assert status == 401 and body == {"error": "unauthorized"}
    assert not authorize("t", "Basic t")
    assert is_loopback("localhost")


def test_panel_manifest_presence_is_truth() -> None:
    assert panel_manifest(_sources()) == ["tracks", "detections", "health", "fpv", "chat", "logs"]
    assert panel_manifest(_sources(fpv=None, chat=None, logs=None)) == [
        "tracks",
        "detections",
        "health",
    ]


# ── read-only contract (I-2): asserted mechanically ───────────────────────────


def test_route_table_method_inventory() -> None:
    app = build_ui_app(_sources(), UIConfig())
    inventory = {
        (route.method, route.resource.canonical)
        for route in app.router.routes()
        if route.method != "HEAD"  # aiohttp adds HEAD alongside every GET
    }
    assert inventory == {
        ("GET", "/"),
        ("GET", "/healthz"),
        ("GET", "/api/tracks"),
        ("GET", "/api/detections"),
        ("GET", "/api/health"),
        ("GET", "/api/fpv"),
        ("POST", "/api/chat"),
        ("GET", "/api/logs"),
    }
    mutating = [m for m, _ in inventory if m not in ("GET",)]
    assert mutating == ["POST"]  # exactly one, and it is the non-command chat route


# ── auth matrix ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "path", ["/api/tracks", "/api/detections", "/api/health", "/api/fpv", "/api/logs"]
)
async def test_data_routes_require_bearer(path: str) -> None:
    client = await _client(build_ui_app(_sources(), UIConfig(token="s3cret")))
    try:
        assert (await client.get(path)).status == 401
        assert (await client.get(path, headers={"Authorization": "Bearer no"})).status == 401
        ok = await client.get(path, headers={"Authorization": "Bearer s3cret"})
        assert ok.status == 200
    finally:
        await client.close()


async def test_chat_requires_bearer() -> None:
    client = await _client(build_ui_app(_sources(), UIConfig(token="s3cret")))
    try:
        assert (await client.post("/api/chat", json={"prompt": "hi"})).status == 401
        ok = await client.post(
            "/api/chat", json={"prompt": "hi"}, headers={"Authorization": "Bearer s3cret"}
        )
        assert ok.status == 200
        assert (await ok.json())["reply"] == "echo: hi"
    finally:
        await client.close()


async def test_page_token_gate_and_injection() -> None:
    client = await _client(build_ui_app(_sources(), UIConfig(token="s3cret", title="Unit 7")))
    try:
        assert (await client.get("/")).status == 401
        assert (await client.get("/", params={"token": "wrong"})).status == 401
        page = await client.get("/", params={"token": "s3cret"})
        assert page.status == 200
        text = await page.text()
        assert '"s3cret"' in text  # JSON-injected for the page's fetches
        assert '"Unit 7"' in text
        assert "__UI_TOKEN__" not in text and "__UI_MANIFEST__" not in text
    finally:
        await client.close()


async def test_no_token_everything_open_and_healthz_always_open() -> None:
    client = await _client(build_ui_app(_sources(), UIConfig()))
    try:
        assert (await client.get("/")).status == 200
        assert (await client.get("/api/tracks")).status == 200
        assert (await client.get("/healthz")).status == 200
    finally:
        await client.close()


async def test_healthz_open_even_with_token() -> None:
    client = await _client(build_ui_app(_sources(), UIConfig(token="s3cret")))
    try:
        res = await client.get("/healthz")
        assert res.status == 200
        assert await res.json() == {"status": "ok"}
    finally:
        await client.close()


# ── degradation: absence is 404-by-absence; failure is a generic 502 ─────────


async def test_absent_sources_routes_absent_and_manifest_omits() -> None:
    client = await _client(
        build_ui_app(_sources(fpv=None, chat=None, logs=None, health=None), UIConfig())
    )
    try:
        assert (await client.get("/api/fpv")).status == 404
        assert (await client.post("/api/chat", json={"prompt": "x"})).status == 404
        assert (await client.get("/api/logs")).status == 404
        # /api/health is always registered; without a health source it still serves
        # the snapshot counters.
        health = await client.get("/api/health")
        assert health.status == 200
        assert await health.json() == {"snapshot": {"tracks_live": 0}}
        text = await (await client.get("/")).text()
        manifest_line = next(
            line for line in text.splitlines() if line.startswith("const UI_PANELS = ")
        )
        manifest = json.loads(manifest_line.removeprefix("const UI_PANELS = ").rstrip(";"))
        assert manifest == ["tracks", "detections", "health"]
    finally:
        await client.close()


@pytest.mark.parametrize(
    "path,sources",
    [
        ("/api/tracks", _sources(snapshot=FakeSnapshot(raise_on_read=True))),
        ("/api/detections", _sources(snapshot=FakeSnapshot(raise_on_read=True))),
        ("/api/health", _sources(snapshot=FakeSnapshot(raise_on_read=True))),
        ("/api/fpv", _sources(fpv=FakeFpv(boom=True))),
        ("/api/logs", _sources(logs=RaisingLogs())),
    ],
)
async def test_raising_source_yields_generic_502(path: str, sources: UISources) -> None:
    client = await _client(build_ui_app(sources, UIConfig()))
    try:
        res = await client.get(path)
        assert res.status == 502
        body = await res.json()
        assert body == {"error": UPSTREAM_ERROR}
        # The internal detail must never reach the browser (llm policy).
        assert "secret" not in str(body) and "sqlite" not in str(body)
    finally:
        await client.close()


async def test_raising_chat_backend_yields_generic_502() -> None:
    client = await _client(build_ui_app(_sources(chat=RaisingChat()), UIConfig()))
    try:
        res = await client.post("/api/chat", json={"prompt": "x"})
        assert res.status == 502
        assert await res.json() == {"error": UPSTREAM_ERROR}
    finally:
        await client.close()


async def test_chat_invalid_payload_400() -> None:
    client = await _client(build_ui_app(_sources(), UIConfig()))
    try:
        res = await client.post("/api/chat", data=b"not json")
        assert res.status == 400
    finally:
        await client.close()


async def test_chat_invalid_payload_logs_parse_error() -> None:
    # Matches the other five source handlers + the chat-backend-call: a swallowed
    # exception must still leave a structured, server-side trail (llm policy).
    client = await _client(build_ui_app(_sources(), UIConfig()))
    try:
        with structlog.testing.capture_logs() as cap:
            res = await client.post("/api/chat", data=b"not json")
        assert res.status == 400
        [entry] = [e for e in cap if e["event"] == "ui_chat_payload_parse_error"]
        assert entry["log_level"] == "warning"
        assert entry["route"] == "/api/chat"
        assert entry["error_type"] == "JSONDecodeError"
        assert entry["error"]
    finally:
        await client.close()


# ── end-to-end through a real SnapshotStore (no fakes on the data path) ───────


class _Clock:
    t = 0.0

    def now(self) -> float:
        return self.t


async def test_tracks_flow_through_real_store() -> None:
    from meshsa.models import Envelope, MessageKind

    store = SnapshotStore(
        _Clock(), max_tracks=4, max_detections=4, track_stale_s=60.0, detection_stale_s=60.0
    )
    store.handle(
        Envelope(
            msg_id="m1",
            ts=1.0,
            source_uid="drone-1",
            kind=MessageKind.PLI,
            payload={
                "node": {"uid": "drone-1", "callsign": "D1"},
                "position": {"lat": 1.0, "lon": 2.0},
            },
        )
    )
    client = await _client(build_ui_app(_sources(snapshot=store), UIConfig()))
    try:
        body = await (await client.get("/api/tracks")).json()
        assert body["features"][0]["properties"]["uid"] == "drone-1"
    finally:
        await client.close()


# ── sources adapters + cli wiring (pure) ──────────────────────────────────────


class _FakeReport:
    class _State:
        value = "healthy"

    state = _State()
    arm_permitted = True
    reasons = ("all links nominal",)
    t_mono = 12.5


class _FakeMonitor:
    def evaluate(self) -> _FakeReport:
        return _FakeReport()


def test_fpv_link_source_adapts_report() -> None:
    assert FpvLinkSource(_FakeMonitor()).report() == {
        "state": "healthy",
        "arm_permitted": True,
        "reasons": ["all links nominal"],
        "t_mono": 12.5,
    }


class _FakeAgent:
    def __init__(self, *, boom: bool = False) -> None:
        self.boom = boom

    async def ask(self, prompt: str, history: Any = None) -> Any:
        if self.boom:
            raise RuntimeError("upstream 500")

        class Reply:
            text = f"re: {prompt}"
            tool_calls: list[Any] = []
            stop_reason = "end_turn"

        return Reply()


async def test_agent_chat_backend_inherits_llm_policy() -> None:
    backend = AgentChatBackend(_FakeAgent())
    body, status = await backend.reply({"prompt": "status?"})
    assert status == 200 and body["reply"] == "re: status?"
    assert (await backend.reply({"prompt": ""}))[1] == 400
    assert (await backend.reply("not a dict"))[1] == 400
    body, status = await AgentChatBackend(_FakeAgent(boom=True)).reply({"prompt": "x"})
    assert status == 502
    assert "upstream 500" not in str(body)  # generic message only


async def test_agent_chat_backend_prompt_cap_configurable() -> None:
    backend = AgentChatBackend(_FakeAgent(), max_prompt_chars=5)
    assert (await backend.reply({"prompt": "123456"}))[1] == 400


class _FakeMetrics:
    rx = 1
    tx = 2
    forwarded = 3
    dropped_undecodable = 0
    schema_mismatch = 0

    def as_dict(self) -> dict[str, int]:
        return {"rx": self.rx, "tx": self.tx}


class _FakeRouter:
    metrics = _FakeMetrics()
    transports: list[Any] = []


class _FakeInfo:
    uid = "n1"


class _FakeNode:
    """Duck-typed node for NodeHealthSource: router.metrics + transports + info."""

    router = _FakeRouter()
    info = _FakeInfo()
    inference_service = None


def test_node_health_source_snapshot() -> None:
    body = NodeHealthSource(_FakeNode(), metrics_format="json").snapshot()  # type: ignore[arg-type]
    assert body["health"]["uid"] == "n1"
    assert body["metrics"]["metrics"] == {"rx": 1, "tx": 2}


def test_build_sources_gating() -> None:
    snapshot = SnapshotStore(
        _Clock(), max_tracks=1, max_detections=1, track_stale_s=1.0, detection_stale_s=1.0
    )
    ring = LogRing(10)
    node = _FakeNode()
    # Flags off: optional sources absent even when collaborators are supplied.
    off = build_sources(node, snapshot, UIConfig(), chat_agent=_FakeAgent(), log_ring=ring)
    assert off.chat is None and off.logs is None and off.fpv is None
    assert off.health is not None and off.snapshot is snapshot
    # Flags on but collaborator missing: still absent (no half-wired panels).
    missing = build_sources(node, snapshot, UIConfig(chat_enabled=True, log_ring_enabled=True))
    assert missing.chat is None and missing.logs is None
    # Flags on + collaborators present: wired.
    on = build_sources(
        node,
        snapshot,
        UIConfig(chat_enabled=True, log_ring_enabled=True),
        fpv_monitor=_FakeMonitor(),
        chat_agent=_FakeAgent(),
        log_ring=ring,
    )
    assert on.chat is not None and on.logs is ring and on.fpv is not None


# ── review regressions: token-override normalisation, no-store, script escaping ──


def test_whitespace_token_override_fails_closed() -> None:
    # A whitespace override is no credential: the non-loopback bind must be refused.
    with pytest.raises(ValueError):
        build_ui_app(_sources(), UIConfig(), host="0.0.0.0", token="   ")


async def test_whitespace_token_override_means_no_auth() -> None:
    # Explicit empty override disables auth (loopback posture), never a guessable "   ".
    client = await _client(build_ui_app(_sources(), UIConfig(token="s3cret"), token="   "))
    try:
        assert (await client.get("/api/tracks")).status == 200
    finally:
        await client.close()


async def test_index_sends_no_store() -> None:
    client = await _client(build_ui_app(_sources(), UIConfig(token="s3cret")))
    try:
        page = await client.get("/", params={"token": "s3cret"})
        assert page.status == 200
        assert page.headers["Cache-Control"] == "no-store"
    finally:
        await client.close()


# Regression for the bug found in the code-hygiene-modularity audit: the page route had
# Cache-Control: no-store but the bearer-guarded /api/* JSON routes did not, so an
# intermediary proxy could persist an authorized response for replay to the next visitor
# of the same cached URL. Salvaged from deliverables/meshsa-ui-validation's S5a scenario
# (spec delta m2-bind-safety "Authenticated JSON Responses Are Non-Cacheable").
@pytest.mark.parametrize(
    "path", ["/api/tracks", "/api/detections", "/api/health", "/api/fpv", "/api/logs"]
)
async def test_s5a_no_store_on_api_get_routes(path: str) -> None:
    client = await _client(build_ui_app(_sources(), UIConfig(token="s3cret")))
    try:
        resp = await client.get(path, headers={"Authorization": "Bearer s3cret"})
        assert resp.status == 200, f"expected 200 on {path}, got {resp.status}"
        assert resp.headers.get("Cache-Control") == "no-store", (
            f"Cache-Control: no-store missing on {path}; got {resp.headers.get('Cache-Control')!r}"
        )
    finally:
        await client.close()


async def test_s5a_no_store_on_chat_and_denied_response() -> None:
    client = await _client(build_ui_app(_sources(), UIConfig(token="s3cret")))
    try:
        # Denied (401) response also carries no-store.
        denied = await client.get("/api/tracks")
        assert denied.status == 401
        assert denied.headers.get("Cache-Control") == "no-store"
        # Successful POST /api/chat response carries no-store.
        ok = await client.post(
            "/api/chat",
            headers={"Authorization": "Bearer s3cret"},
            json={"prompt": "status?"},
        )
        assert ok.status == 200
        assert ok.headers.get("Cache-Control") == "no-store"
    finally:
        await client.close()


async def test_page_values_cannot_close_script_block() -> None:
    evil = "</script><script>alert(1)</script>"
    client = await _client(build_ui_app(_sources(), UIConfig(title=evil)))
    try:
        text = await (await client.get("/")).text()
        assert "</script><script>" not in text.replace("\n", "")
        assert "\\u003c/script\\u003e" in text  # JSON-escaped, decodes to the same string
    finally:
        await client.close()
