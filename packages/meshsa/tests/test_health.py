"""Pure health_snapshot rendering (the aiohttp server is a pragma'd seam)."""

from meshsa import NodeConfig, build_node, health_snapshot
from meshsa.health import render_metrics


def _node():
    return build_node(
        NodeConfig(uid="u", callsign="U", transports=[{"name": "mesh", "type": "loopback"}])
    )


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
