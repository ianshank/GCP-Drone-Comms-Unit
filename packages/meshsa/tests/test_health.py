"""Pure health_snapshot rendering (the aiohttp server is a pragma'd seam)."""

from meshsa import NodeConfig, build_node, health_snapshot


def _node():
    return build_node(
        NodeConfig(uid="u", callsign="U", transports=[{"name": "mesh", "type": "loopback"}])
    )


def test_health_config_defaults():
    cfg = NodeConfig(uid="u", callsign="U")
    assert cfg.health.enabled is False
    assert cfg.health.host == "127.0.0.1"
    assert cfg.health.port == 8088


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
    assert snap["transports"]["mesh"] == {"dropped_inbox_full": 0, "reconnects": 0}
