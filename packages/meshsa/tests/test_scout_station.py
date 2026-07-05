"""Tests for meshsa.scout.station — pure auth helpers + aiohttp handlers."""

from __future__ import annotations

import pytest
from aiohttp.test_utils import TestClient, TestServer

from meshsa.scout.schemas import GeoDetection
from meshsa.scout.station import authorize, build_app, is_loopback, set_status_body, validate_bind
from meshsa.scout.store import InMemoryStore


def _store() -> InMemoryStore:
    s = InMemoryStore()
    s.add(
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
    return s


def test_is_loopback() -> None:
    assert is_loopback("127.0.0.1")
    assert is_loopback("localhost")
    assert not is_loopback("0.0.0.0")


def test_authorize() -> None:
    assert authorize(None, None)  # open when no token
    assert authorize("t", "Bearer t")
    assert not authorize("t", None)
    assert not authorize("t", "Basic t")
    assert not authorize("t", "Bearer wrong")


def test_validate_bind_fail_closed() -> None:
    validate_bind("127.0.0.1", None)  # ok
    validate_bind("0.0.0.0", "token")  # ok with token
    with pytest.raises(ValueError):
        validate_bind("0.0.0.0", None)


def test_set_status_body() -> None:
    store = _store()
    body, status = set_status_body(store, "d1", {"status": "tagged"})
    assert status == 200 and body["status"] == "tagged"
    assert set_status_body(store, "d1", {"status": "bogus"})[1] == 400
    assert set_status_body(store, "d1", "notdict")[1] == 400
    assert set_status_body(store, "missing", {"status": "tagged"})[1] == 404


def test_build_app_self_validates_bind() -> None:
    with pytest.raises(ValueError):  # non-loopback without a token is refused inside build_app
        build_app(_store(), host="0.0.0.0", token=None)
    build_app(_store(), host="0.0.0.0", token="tok")  # ok with a token
    build_app(_store(), host="127.0.0.1", token=None)  # loopback ok without a token


async def test_index_gated_and_injects_token() -> None:
    app = build_app(_store(), token="sekret")
    async with TestClient(TestServer(app)) as client:
        assert (await client.get("/")).status == 401  # page gated when a token is set
        ok = await client.get("/", params={"token": "sekret"})
        assert ok.status == 200
        body = await ok.text()
        assert '"sekret"' in body  # token injected so the page's fetches can authenticate


async def test_index_open_without_token() -> None:
    async with TestClient(TestServer(build_app(_store()))) as client:
        resp = await client.get("/")
        assert resp.status == 200
        assert "null" in await resp.text()  # SCOUT_TOKEN injected as null


async def test_open_endpoints() -> None:
    async with TestClient(TestServer(build_app(_store()))) as client:
        assert (await client.get("/healthz")).status == 200
        index = await client.get("/")
        assert index.status == 200
        assert "text/html" in index.headers["Content-Type"]
        fc = await (await client.get("/detections")).json()
        assert fc["features"][0]["properties"]["id"] == "d1"
        csv = await client.get("/export.csv")
        assert "text/csv" in csv.headers["Content-Type"]


async def test_block_endpoint() -> None:
    async with TestClient(TestServer(build_app(_store()))) as client:
        assert (await client.get("/block")).status == 404
    block_gj = {"type": "FeatureCollection", "features": []}
    async with TestClient(TestServer(build_app(_store(), block_geojson=block_gj))) as client:
        assert (await client.get("/block")).status == 200


async def test_status_transition_via_http() -> None:
    async with TestClient(TestServer(build_app(_store()))) as client:
        resp = await client.post("/detections/d1/status", json={"status": "rejected"})
        assert resp.status == 200
        fc = await (await client.get("/detections")).json()
        assert fc["features"][0]["properties"]["status"] == "rejected"
        assert (
            await client.post("/detections/nope/status", json={"status": "tagged"})
        ).status == 404


async def test_malformed_status_body_is_400() -> None:
    async with TestClient(TestServer(build_app(_store()))) as client:
        resp = await client.post(
            "/detections/d1/status", data="not json", headers={"Content-Type": "application/json"}
        )
        assert resp.status == 400


async def test_auth_gates_all_data_endpoints() -> None:
    app = build_app(
        _store(), token="sekret", block_geojson={"type": "FeatureCollection", "features": []}
    )
    async with TestClient(TestServer(app)) as client:
        assert (await client.get("/healthz")).status == 200  # open
        for path in ("/detections", "/export.geojson", "/export.csv", "/block"):
            assert (await client.get(path)).status == 401, path
        # …and each is reachable with the bearer token.
        for path in ("/detections", "/export.geojson", "/export.csv", "/block"):
            ok = await client.get(path, headers={"Authorization": "Bearer sekret"})
            assert ok.status == 200, path


async def test_auth_gates_data_endpoints() -> None:
    app = build_app(_store(), token="sekret")
    async with TestClient(TestServer(app)) as client:
        assert (await client.get("/healthz")).status == 200  # open
        assert (await client.get("/detections")).status == 401  # no token
        ok = await client.get("/detections", headers={"Authorization": "Bearer sekret"})
        assert ok.status == 200
        assert (await client.get("/export.geojson")).status == 401
        assert (await client.post("/detections/d1/status", json={"status": "tagged"})).status == 401
