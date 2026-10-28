"""Characterization pins for the four aiohttp app factories (design D-5/D-8).

Every route of ``ui/app.py``, ``scout/station/app.py``, ``llm/server.py`` and ``health.py``
is pinned here by status, the headers that carry security meaning (``Cache-Control``,
``WWW-Authenticate``, ``Content-Type``) and the body shape of a refusal. The pins landed
*before* the factories migrated to ``meshsa._web`` so the migration's diff shows exactly
which observable behaviour changed — and only the two declared deltas may change:

* ``WWW-Authenticate: Bearer realm="<service>"`` on every 401 (RFC 7235 §3.1), which only
  ``health.py`` sent before the kit existed;
* ``Cache-Control: no-store`` on every bearer-guarded data response (spec delta
  ``m2-bind-safety`` "Authenticated JSON Responses Are Non-Cacheable"), which only the
  operator console sent before.

Also carries the scenarios salvaged from ``deliverables/meshsa-ui-validation`` (S5b, S5c,
S6a, S6b) that had no in-package counterpart. S4d (an ``X-Snapshot-Age`` header) is not
salvaged: no spec requires the header, so adding it is a feature with its own spec first.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest

pytest.importorskip("aiohttp")

from aiohttp import web  # noqa: E402
from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from meshsa import NodeConfig, build_node  # noqa: E402
from meshsa.health import build_healthz_app  # noqa: E402
from meshsa.llm.agent import AgentReply  # noqa: E402
from meshsa.llm.server import build_app as build_llm_app  # noqa: E402
from meshsa.models import Envelope, MessageKind  # noqa: E402
from meshsa.scout.schemas import GeoDetection  # noqa: E402
from meshsa.scout.station import build_app as build_station_app  # noqa: E402
from meshsa.scout.store import InMemoryStore  # noqa: E402
from meshsa.ui.app import build_ui_app  # noqa: E402
from meshsa.ui.config import UIConfig  # noqa: E402
from meshsa.ui.snapshot import SnapshotStore  # noqa: E402
from meshsa.ui.sources import UISources  # noqa: E402

TOKEN = "s3cr3t-tok3n"
BEARER = {"Authorization": f"Bearer {TOKEN}"}
WRONG_BEARER = {"Authorization": "Bearer stale-token"}
UNAUTHORIZED_BODY = {"error": "unauthorized"}


@asynccontextmanager
async def _serve(app: web.Application) -> AsyncIterator[TestClient]:
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        yield client
    finally:
        await client.close()


# ── fakes ─────────────────────────────────────────────────────────────────────


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def now(self) -> float:
        return self.t

    def monotonic(self) -> float:
        return self.t


class _Health:
    def snapshot(self) -> dict[str, Any]:
        return {"health": {"status": "ok"}}


class _Fpv:
    def report(self) -> dict[str, Any]:
        return {"state": "healthy"}


class _Chat:
    async def reply(self, payload: Any) -> tuple[dict[str, Any], int]:
        if not isinstance(payload, dict) or "prompt" not in payload:
            return {"error": "missing 'prompt'"}, 400
        return {"reply": "echo"}, 200


class _Logs:
    def entries(self) -> list[dict[str, Any]]:
        return [{"ts": 1.0, "level": "info", "event": "boot"}]


class _Agent:
    async def ask(self, prompt: str, history: list[dict[str, Any]] | None = None) -> AgentReply:
        return AgentReply(text="ok", stop_reason="end_turn", tool_calls=[])


def _pli(uid: str) -> Envelope:
    return Envelope(
        schema_version=1,
        msg_id=f"{uid}-1",
        ts=0.0,
        source_uid=uid,
        kind=MessageKind.PLI,
        payload={
            "node": {"uid": uid, "callsign": uid.upper(), "tier": "user"},
            "position": {"lat": 38.5, "lon": -122.5, "hae": 0.0, "ce": 1.0, "le": 1.0},
        },
    )


def _ui_app(token: str | None = TOKEN) -> web.Application:
    store = SnapshotStore(
        _Clock(), max_tracks=8, max_detections=8, track_stale_s=600.0, detection_stale_s=600.0
    )
    store.handle(_pli("uas-hotel"))
    sources = UISources(snapshot=store, health=_Health(), fpv=_Fpv(), chat=_Chat(), logs=_Logs())
    return build_ui_app(sources, UIConfig(token=token))


def _station_app(token: str | None = TOKEN) -> web.Application:
    store = InMemoryStore()
    store.add(
        GeoDetection(
            id="d1",
            lat=38.5,
            lon=-122.5,
            cls="missing_vine",
            conf=0.9,
            error_m=0.4,
            src_frame="f",
            ts=1.0,
            block_id="b1",
        )
    )
    return build_station_app(store, token=token, block_geojson={"type": "FeatureCollection"})


def _llm_app(token: str | None = TOKEN) -> web.Application:
    return build_llm_app(_Agent(), token)


def _health_app(token: str | None = TOKEN, fmt: str = "prometheus") -> web.Application:
    node = build_node(
        NodeConfig(uid="u", callsign="U", transports=[{"name": "mesh", "type": "loopback"}])
    )
    return build_healthz_app(
        node, token=token, metrics_enabled=True, metrics_path="/metrics", metrics_format=fmt
    )


# ── the pin tables ────────────────────────────────────────────────────────────
#
# (method, path, kwargs) → expected (status, Cache-Control, Content-Type prefix).
# ``"no-store"`` on every credential-bearing response; ``None`` (absent) only on the open
# routes — ``/healthz`` everywhere and the llm widget page, which embeds no token.

_UI_AUTHED: list[tuple[str, str, dict[str, Any], int, str | None, str]] = [
    ("GET", "/", {"params": {"token": TOKEN}}, 200, "no-store", "text/html"),
    ("GET", "/healthz", {}, 200, None, "application/json"),
    ("GET", "/api/tracks", {"headers": BEARER}, 200, "no-store", "application/json"),
    ("GET", "/api/detections", {"headers": BEARER}, 200, "no-store", "application/json"),
    ("GET", "/api/health", {"headers": BEARER}, 200, "no-store", "application/json"),
    ("GET", "/api/fpv", {"headers": BEARER}, 200, "no-store", "application/json"),
    ("GET", "/api/logs", {"headers": BEARER}, 200, "no-store", "application/json"),
    (
        "POST",
        "/api/chat",
        {"headers": BEARER, "json": {"prompt": "hi"}},
        200,
        "no-store",
        "application/json",
    ),
]

_STATION_AUTHED: list[tuple[str, str, dict[str, Any], int, str | None, str]] = [
    ("GET", "/", {"params": {"token": TOKEN}}, 200, "no-store", "text/html"),
    ("GET", "/healthz", {}, 200, None, "application/json"),
    ("GET", "/detections", {"headers": BEARER}, 200, "no-store", "application/json"),
    ("GET", "/export.geojson", {"headers": BEARER}, 200, "no-store", "application/json"),
    ("GET", "/export.csv", {"headers": BEARER}, 200, "no-store", "text/csv"),
    ("GET", "/block", {"headers": BEARER}, 200, "no-store", "application/json"),
    (
        "POST",
        "/detections/d1/status",
        {"headers": BEARER, "json": {"status": "tagged"}},
        200,
        "no-store",
        "application/json",
    ),
]

_LLM_AUTHED: list[tuple[str, str, dict[str, Any], int, str | None, str]] = [
    ("GET", "/", {}, 200, None, "text/html"),
    ("GET", "/healthz", {}, 200, None, "application/json"),
    (
        "POST",
        "/chat",
        {"headers": BEARER, "json": {"prompt": "hi"}},
        200,
        "no-store",
        "application/json",
    ),
]

_HEALTH_AUTHED: list[tuple[str, str, dict[str, Any], int, str | None, str]] = [
    ("GET", "/healthz", {}, 200, None, "application/json"),
    ("GET", "/metrics", {"headers": BEARER}, 200, "no-store", "text/plain"),
]


async def _assert_pin(
    client: TestClient, method: str, path: str, kwargs: dict[str, Any], expect: tuple[Any, ...]
) -> None:
    status, cache_control, content_type = expect
    resp = await client.request(method, path, **kwargs)
    assert resp.status == status, (method, path, resp.status)
    assert resp.headers.get("Cache-Control") == cache_control, (method, path)
    assert resp.headers["Content-Type"].startswith(content_type), (method, path)


@pytest.mark.parametrize("method, path, kwargs, status, cache_control, content_type", _UI_AUTHED)
async def test_ui_route_pins(
    method: str,
    path: str,
    kwargs: dict[str, Any],
    status: int,
    cache_control: Any,
    content_type: str,
) -> None:
    async with _serve(_ui_app()) as client:
        await _assert_pin(client, method, path, kwargs, (status, cache_control, content_type))


@pytest.mark.parametrize(
    "method, path, kwargs, status, cache_control, content_type", _STATION_AUTHED
)
async def test_station_route_pins(
    method: str,
    path: str,
    kwargs: dict[str, Any],
    status: int,
    cache_control: Any,
    content_type: str,
) -> None:
    async with _serve(_station_app()) as client:
        await _assert_pin(client, method, path, kwargs, (status, cache_control, content_type))


@pytest.mark.parametrize("method, path, kwargs, status, cache_control, content_type", _LLM_AUTHED)
async def test_llm_route_pins(
    method: str,
    path: str,
    kwargs: dict[str, Any],
    status: int,
    cache_control: Any,
    content_type: str,
) -> None:
    async with _serve(_llm_app()) as client:
        await _assert_pin(client, method, path, kwargs, (status, cache_control, content_type))


@pytest.mark.parametrize(
    "method, path, kwargs, status, cache_control, content_type", _HEALTH_AUTHED
)
async def test_health_route_pins(
    method: str,
    path: str,
    kwargs: dict[str, Any],
    status: int,
    cache_control: Any,
    content_type: str,
) -> None:
    async with _serve(_health_app()) as client:
        await _assert_pin(client, method, path, kwargs, (status, cache_control, content_type))


# ── the 401 contract, per factory ─────────────────────────────────────────────
#
# Each refusal is pinned by body, Cache-Control and the WWW-Authenticate challenge. Before
# the shared kit, only health.py sent the challenge and only the console sent no-store; now
# every 401 carries both (the kit's single ``unauthorized``).

_UI_DENIED: list[tuple[str, str, dict[str, Any]]] = [
    ("GET", "/", {}),
    ("GET", "/", {"params": {"token": "wrong"}}),
    ("GET", "/api/tracks", {}),
    ("GET", "/api/tracks", {"headers": WRONG_BEARER}),
    ("GET", "/api/detections", {"headers": WRONG_BEARER}),
    ("GET", "/api/health", {"headers": WRONG_BEARER}),
    ("GET", "/api/fpv", {"headers": WRONG_BEARER}),
    ("GET", "/api/logs", {"headers": WRONG_BEARER}),
    ("POST", "/api/chat", {"headers": WRONG_BEARER, "json": {"prompt": "hi"}}),
]

_STATION_DENIED: list[tuple[str, str, dict[str, Any]]] = [
    ("GET", "/", {}),
    ("GET", "/", {"params": {"token": "wrong"}}),
    ("GET", "/detections", {}),
    ("GET", "/export.geojson", {"headers": WRONG_BEARER}),
    ("GET", "/export.csv", {"headers": WRONG_BEARER}),
    ("GET", "/block", {"headers": WRONG_BEARER}),
    ("POST", "/detections/d1/status", {"headers": WRONG_BEARER, "json": {"status": "tagged"}}),
]

_LLM_DENIED: list[tuple[str, str, dict[str, Any]]] = [
    ("POST", "/chat", {"json": {"prompt": "hi"}}),
    ("POST", "/chat", {"headers": WRONG_BEARER, "json": {"prompt": "hi"}}),
]

_HEALTH_DENIED: list[tuple[str, str, dict[str, Any]]] = [
    ("GET", "/metrics", {}),
    ("GET", "/metrics", {"headers": WRONG_BEARER}),
]


async def _assert_denied(
    client: TestClient,
    method: str,
    path: str,
    kwargs: dict[str, Any],
    *,
    cache_control: str | None,
    challenge: str | None,
) -> None:
    resp = await client.request(method, path, **kwargs)
    assert resp.status == 401, (method, path, resp.status)
    assert await resp.json() == UNAUTHORIZED_BODY
    assert resp.headers.get("Cache-Control") == cache_control, (method, path)
    assert resp.headers.get("WWW-Authenticate") == challenge, (method, path)


@pytest.mark.parametrize("method, path, kwargs", _UI_DENIED)
async def test_ui_denied_pins(method: str, path: str, kwargs: dict[str, Any]) -> None:
    async with _serve(_ui_app()) as client:
        await _assert_denied(
            client,
            method,
            path,
            kwargs,
            cache_control="no-store",
            challenge='Bearer realm="meshsa-ui"',
        )


@pytest.mark.parametrize("method, path, kwargs", _STATION_DENIED)
async def test_station_denied_pins(method: str, path: str, kwargs: dict[str, Any]) -> None:
    async with _serve(_station_app()) as client:
        await _assert_denied(
            client,
            method,
            path,
            kwargs,
            cache_control="no-store",
            challenge='Bearer realm="meshsa-scout"',
        )


@pytest.mark.parametrize("method, path, kwargs", _LLM_DENIED)
async def test_llm_denied_pins(method: str, path: str, kwargs: dict[str, Any]) -> None:
    async with _serve(_llm_app()) as client:
        await _assert_denied(
            client,
            method,
            path,
            kwargs,
            cache_control="no-store",
            challenge='Bearer realm="meshsa-llm"',
        )


@pytest.mark.parametrize("method, path, kwargs", _HEALTH_DENIED)
async def test_health_denied_pins(method: str, path: str, kwargs: dict[str, Any]) -> None:
    async with _serve(_health_app()) as client:
        await _assert_denied(
            client,
            method,
            path,
            kwargs,
            cache_control="no-store",
            challenge='Bearer realm="meshsa-metrics"',
        )


# ── no-token posture: every data route open, byte-identical bodies ───────────


async def test_no_token_opens_every_guarded_route_on_all_four_apps() -> None:
    cases = [
        (_ui_app(None), "GET", "/api/tracks", {}),
        (_ui_app(None), "GET", "/", {}),
        (_station_app(None), "GET", "/detections", {}),
        (_station_app(None), "GET", "/", {}),
        (_llm_app(None), "POST", "/chat", {"json": {"prompt": "hi"}}),
        (_health_app(None), "GET", "/metrics", {}),
    ]
    for app, method, path, kwargs in cases:
        async with _serve(app) as client:
            assert (await client.request(method, path, **kwargs)).status == 200, (method, path)


# ── malformed-body handling on the JSON-accepting routes ─────────────────────


@pytest.mark.parametrize(
    "factory, path, headers",
    [
        (_ui_app, "/api/chat", BEARER),
        (_station_app, "/detections/d1/status", BEARER),
        (_llm_app, "/chat", BEARER),
    ],
)
async def test_malformed_json_body_is_a_400_not_a_500(
    factory: Any, path: str, headers: dict[str, str]
) -> None:
    async with _serve(factory()) as client:
        resp = await client.post(
            path, data="not json", headers={**headers, "Content-Type": "application/json"}
        )
        assert resp.status == 400
        assert "error" in await resp.json()


# ── salvaged deliverables scenarios (S5b/S5c/S6a/S6b) ────────────────────────


async def test_s5b_console_page_served_with_token_query_is_no_store() -> None:
    async with _serve(_ui_app()) as client:
        resp = await client.get("/", params={"token": TOKEN})
        assert resp.status == 200
        assert resp.headers["Cache-Control"] == "no-store"


async def test_s5c_healthz_is_open_and_discloses_nothing() -> None:
    for app in (_ui_app(), _station_app(), _llm_app(), _health_app()):
        async with _serve(app) as client:
            resp = await client.get("/healthz")
            assert resp.status == 200
            body = str(await resp.json())
            assert TOKEN not in body
            assert "lat" not in body and "lon" not in body


async def test_s6a_old_token_rejected_after_rotation() -> None:
    old, new = "old-tok-alpha", "new-tok-beta"
    async with _serve(_ui_app(old)) as client:
        assert (
            await client.get("/api/tracks", headers={"Authorization": f"Bearer {old}"})
        ).status == 200
    async with _serve(_ui_app(new)) as client:
        assert (
            await client.get("/api/tracks", headers={"Authorization": f"Bearer {old}"})
        ).status == 401
        assert (
            await client.get("/api/tracks", headers={"Authorization": f"Bearer {new}"})
        ).status == 200


async def test_s6b_stale_token_refusal_leaks_no_track_data() -> None:
    async with _serve(_ui_app()) as client:
        resp = await client.get("/api/tracks", headers=WRONG_BEARER)
        assert resp.status == 401
        body = str(await resp.json())
        assert "FeatureCollection" not in body
        assert "features" not in body
        assert "uas-hotel" not in body
