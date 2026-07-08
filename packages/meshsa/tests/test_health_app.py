"""Integration tests for the /healthz+/metrics aiohttp app (real routes via TestClient).

These drive ``build_healthz_app`` end-to-end through an in-process aiohttp server so the actual
request wiring — the open ``/healthz`` liveness route and the bearer-gated ``/metrics`` route — is
exercised, not just the pure ``authorize``/``render_metrics`` units. The auth branch lives in the
factory (not the pragma-excluded ``serve_healthz`` socket wiring) precisely so a real request can
reach it here. Mirrors ``test_llm_server_app.py`` / ``test_scout_station.py``.
"""

from __future__ import annotations

import pytest

# aiohttp is in the `dev` extra (and the [health]/[llm]/[scout] extras), so this suite runs in
# normal CI. The importorskip is a defensive guard so a minimal env without the test extras skips
# rather than failing collection with ModuleNotFoundError.
pytest.importorskip("aiohttp")

from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from meshsa import NodeConfig, build_node  # noqa: E402
from meshsa.health import build_healthz_app  # noqa: E402


def _node():
    cfg = NodeConfig(
        uid="u",
        callsign="U",
        transports=[{"name": "mesh", "type": "loopback"}],
    )
    return build_node(cfg)


async def _client(
    *,
    token: str | None,
    metrics_enabled: bool = True,
    metrics_format: str = "prometheus",
    metrics_path: str = "/metrics",
) -> TestClient:
    app = build_healthz_app(
        _node(),
        token=token,
        metrics_enabled=metrics_enabled,
        metrics_path=metrics_path,
        metrics_format=metrics_format,
    )
    client = TestClient(TestServer(app))
    await client.start_server()
    return client


async def test_healthz_is_open() -> None:
    client = await _client(token="s3cr3t")
    try:
        hz = await client.get("/healthz")
        assert hz.status == 200
        assert (await hz.json())["status"] == "ok"
    finally:
        await client.close()


async def test_metrics_open_when_no_token_configured() -> None:
    client = await _client(token=None)
    try:
        res = await client.get("/metrics")
        assert res.status == 200
        assert "meshsa_rx_total 0" in await res.text()
    finally:
        await client.close()


async def test_metrics_rejects_without_and_with_wrong_bearer() -> None:
    client = await _client(token="s3cr3t")
    try:
        missing = await client.get("/metrics")
        assert missing.status == 401
        assert (await missing.json())["error"] == "unauthorized"
        # RFC 7235 §3.1: a 401 must advertise the auth scheme.
        assert missing.headers["WWW-Authenticate"] == 'Bearer realm="meshsa-metrics"'

        wrong = await client.get("/metrics", headers={"Authorization": "Bearer nope"})
        assert wrong.status == 401
    finally:
        await client.close()


async def test_metrics_path_without_leading_slash_is_normalised() -> None:
    # A misconfigured metrics_path ("metrics") must not crash startup; it is normalised to
    # "/metrics" so aiohttp accepts the route.
    client = await _client(token=None, metrics_path="metrics")
    try:
        res = await client.get("/metrics")
        assert res.status == 200
        assert "meshsa_rx_total 0" in await res.text()
    finally:
        await client.close()


async def test_metrics_accepts_correct_bearer() -> None:
    client = await _client(token="s3cr3t")
    try:
        ok = await client.get("/metrics", headers={"Authorization": "Bearer s3cr3t"})
        assert ok.status == 200
        assert "meshsa_rx_total 0" in await ok.text()
    finally:
        await client.close()


async def test_metrics_json_format_body() -> None:
    # The json metrics branch returns a JSON body (not prometheus text).
    client = await _client(token=None, metrics_format="json")
    try:
        res = await client.get("/metrics")
        assert res.status == 200
        assert set((await res.json())["metrics"]) == {
            "rx",
            "tx",
            "forwarded",
            "dropped_undecodable",
            "schema_mismatch",
        }
    finally:
        await client.close()


async def test_metrics_route_absent_when_disabled() -> None:
    # metrics_enabled=False registers no /metrics route at all (404), independent of auth.
    client = await _client(token=None, metrics_enabled=False)
    try:
        res = await client.get("/metrics")
        assert res.status == 404
    finally:
        await client.close()
