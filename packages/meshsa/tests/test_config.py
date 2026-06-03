import json

from meshsa import NodeConfig, NodeTier


def test_defaults_are_explicit_not_hardcoded():
    c = NodeConfig(uid="u", callsign="ALPHA")
    assert c.pli_interval_s == 30.0
    assert c.router.dedupe_cache_size == 2048
    assert c.mesh.region == "US"
    assert c.transports == []


def test_from_mapping_roundtrip():
    c = NodeConfig.from_mapping(
        {
            "uid": "u",
            "callsign": "BR1",
            "tier": "backbone",
            "transports": [{"name": "lo", "type": "loopback"}],
        }
    )
    assert c.tier == NodeTier.BACKBONE
    assert c.transports[0].type == "loopback"


def test_from_env_scalar_and_mesh_override(monkeypatch):
    env = {
        "MESHSA_UID": "n1",
        "MESHSA_CALLSIGN": "FOX",
        "MESHSA_PLI_INTERVAL_S": "5",
        "MESHSA_TIER": "base",
        "MESHSA_MESH_CHANNEL": "ops",
        "MESHSA_MESH_FREQ_KHZ": "906500",
    }
    c = NodeConfig.from_env(env)
    assert c.uid == "n1" and c.tier == NodeTier.BASE
    assert c.pli_interval_s == 5.0
    assert c.mesh.channel == "ops" and c.mesh.freq_khz == 906500


def test_from_env_json_blob_then_scalar_wins():
    env = {
        "MESHSA_CONFIG_JSON": json.dumps({"uid": "x", "callsign": "OLD", "pli_interval_s": 99}),
        "MESHSA_CALLSIGN": "NEW",
    }
    c = NodeConfig.from_env(env)
    assert c.callsign == "NEW"  # scalar override beats blob
    assert c.pli_interval_s == 99  # blob value retained


def test_from_file(tmp_path):
    p = tmp_path / "node.json"
    p.write_text(json.dumps({"uid": "u", "callsign": "C"}))
    c = NodeConfig.from_file(str(p))
    assert c.callsign == "C"
