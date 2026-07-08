"""Pure health_snapshot rendering (the aiohttp server is a pragma'd seam)."""

import pytest

from meshsa import NodeConfig, build_node, health_snapshot
from meshsa.health import _resolve_metrics_options, render_metrics, validate_healthz_bind


def _node(health: dict | None = None):
    cfg = NodeConfig(
        uid="u",
        callsign="U",
        transports=[{"name": "mesh", "type": "loopback"}],
        **({"health": health} if health else {}),
    )
    return build_node(cfg)


@pytest.fixture
def node_with_inference(make_transport):
    # config.inference.enabled=True gives build_node an InferenceService (Node.inference_service
    # is non-None); the FakeHttpTransport keeps this fake-network, same pattern as test_inference.py.
    cfg = NodeConfig(
        uid="u",
        callsign="U",
        transports=[{"name": "mesh", "type": "loopback"}],
        inference={"enabled": True, "api_key": "nvapi-test"},
    )
    return build_node(cfg, inference_transport=make_transport([]))


@pytest.fixture
def node_no_inference():
    # Default NemotronConfig() has enabled=False, so build_node leaves
    # node.inference_service as None — the disabled/backward-compat path.
    return _node()


def test_health_config_defaults():
    cfg = NodeConfig(uid="u", callsign="U")
    assert cfg.health.enabled is False
    assert cfg.health.host == "127.0.0.1"
    assert cfg.health.port == 8088
    assert cfg.health.token is None
    assert cfg.health.metrics_enabled is False
    assert cfg.health.metrics_path == "/metrics"
    assert cfg.health.metrics_format == "prometheus"


def test_validate_healthz_bind_allows_loopback_without_token():
    # Default posture: loopback bind needs no token (backward compatible).
    validate_healthz_bind("127.0.0.1", None)
    validate_healthz_bind("localhost", None)


def test_validate_healthz_bind_allows_non_loopback_with_token():
    # A token makes an off-loopback bind acceptable (the /metrics surface is then gated).
    validate_healthz_bind("0.0.0.0", "s3cr3t")


def test_validate_healthz_bind_rejects_non_loopback_without_token():
    # Fail closed: /metrics discloses counters, so a tokenless off-loopback bind is refused.
    with pytest.raises(ValueError, match="meshsa-healthz"):
        validate_healthz_bind("0.0.0.0", None)


def test_health_snapshot_shape():
    snap = health_snapshot(_node())
    assert snap["status"] == "ok"
    assert snap["uid"] == "u"
    assert set(snap["metrics"]) == {
        "rx",
        "tx",
        "forwarded",
        "dropped_undecodable",
        "schema_mismatch",
    }
    assert snap["transports"]["mesh"] == {
        "dropped_inbox_full": 0,
        "reconnects": 0,
        "rx_frames": 0,
    }


def test_render_metrics_prometheus_format():
    text = render_metrics(_node(), "prometheus")
    assert isinstance(text, str)
    lines = text.splitlines()
    assert "meshsa_rx_total 0" in lines
    assert 'meshsa_transport_rx_frames{transport="mesh"} 0' in lines


def test_render_metrics_json_format():
    body = render_metrics(_node(), "json")
    assert isinstance(body, dict)
    assert set(body["metrics"]) == {
        "rx",
        "tx",
        "forwarded",
        "dropped_undecodable",
        "schema_mismatch",
    }
    assert body["transports"]["mesh"] == {
        "dropped_inbox_full": 0,
        "reconnects": 0,
        "rx_frames": 0,
    }


def test_resolve_metrics_options_defaults_from_config():
    # With nothing passed, the metrics options fall back to node.config.health.*,
    # so setting health.metrics_enabled=true in config exposes /metrics with no
    # CLI change (the route-gating branch sees enabled=True).
    node = _node(
        {
            "metrics_enabled": True,
            "metrics_path": "/m",
            "metrics_format": "json",
        }
    )
    enabled, path, fmt = _resolve_metrics_options(node, None, None, None)
    assert enabled is True
    assert path == "/m"
    assert fmt == "json"


def test_resolve_metrics_options_config_default_disabled():
    # Default config leaves metrics disabled, so the route is not gated on.
    enabled, path, fmt = _resolve_metrics_options(_node(), None, None, None)
    assert enabled is False
    assert path == "/metrics"
    assert fmt == "prometheus"


def test_resolve_metrics_options_explicit_args_override_config():
    # An explicit (non-None) argument always wins over the config default.
    node = _node({"metrics_enabled": True, "metrics_path": "/m", "metrics_format": "json"})
    enabled, path, fmt = _resolve_metrics_options(node, False, "/other", "prometheus")
    assert enabled is False
    assert path == "/other"
    assert fmt == "prometheus"


# ── render_metrics: inference counters (Task 4) ─────────────────────────


def test_render_metrics_json_includes_inference_when_enabled(node_with_inference):
    body = render_metrics(node_with_inference, "json")
    assert set(body["inference"]) == {
        "offline_dropped",
        "offline_queue_depth",
        "intake_dropped",
        "pending_tasks",
    }


def test_render_metrics_prometheus_includes_inference(node_with_inference):
    text = render_metrics(node_with_inference, "prometheus")
    assert "meshsa_inference_pending_tasks" in text


def test_render_metrics_propagates_exact_inference_counter_values(node_with_inference):
    # Known, non-zero counters on the real service must propagate end-to-end through
    # /metrics with exact values — not just the key names asserted elsewhere in this file.
    node_with_inference.inference_service._offline_dropped = 3
    node_with_inference.inference_service._intake_dropped = 5
    # offline_queue_depth and pending_tasks stay 0: no offline items queued, no bg tasks.

    body = render_metrics(node_with_inference, "json")
    assert body["inference"] == {
        "offline_dropped": 3,
        "offline_queue_depth": 0,
        "intake_dropped": 5,
        "pending_tasks": 0,
    }

    text = render_metrics(node_with_inference, "prometheus")
    assert "meshsa_inference_offline_dropped_total 3" in text
    assert "meshsa_inference_intake_dropped_total 5" in text


def test_render_metrics_json_omits_inference_when_disabled(node_no_inference):
    assert "inference" not in render_metrics(node_no_inference, "json")


def test_render_metrics_prometheus_omits_inference_when_disabled(node_no_inference):
    text = render_metrics(node_no_inference, "prometheus")
    assert "meshsa_inference_" not in text
