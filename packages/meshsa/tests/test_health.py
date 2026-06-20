"""Pure health_snapshot rendering (the aiohttp server is a pragma'd seam)."""

from meshsa import NodeConfig, build_node, health_snapshot
from meshsa.health import _resolve_metrics_options, render_metrics


def _node(health: dict | None = None):
    cfg = NodeConfig(
        uid="u",
        callsign="U",
        transports=[{"name": "mesh", "type": "loopback"}],
        **({"health": health} if health else {}),
    )
    return build_node(cfg)


def test_health_config_defaults():
    cfg = NodeConfig(uid="u", callsign="U")
    assert cfg.health.enabled is False
    assert cfg.health.host == "127.0.0.1"
    assert cfg.health.port == 8088
    assert cfg.health.metrics_enabled is False
    assert cfg.health.metrics_path == "/metrics"
    assert cfg.health.metrics_format == "prometheus"


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
