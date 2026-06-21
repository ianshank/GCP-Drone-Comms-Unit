import json

import pytest

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


def test_from_env_bad_numeric_names_the_offending_variable():
    with pytest.raises(ValueError, match="MESHSA_PLI_INTERVAL_S: expected a number"):
        NodeConfig.from_env(
            {"MESHSA_UID": "n", "MESHSA_CALLSIGN": "F", "MESHSA_PLI_INTERVAL_S": "soon"}
        )
    with pytest.raises(ValueError, match="MESHSA_MESH_FREQ_KHZ: expected an integer"):
        NodeConfig.from_env(
            {"MESHSA_UID": "n", "MESHSA_CALLSIGN": "F", "MESHSA_MESH_FREQ_KHZ": "lots"}
        )


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


# ---------- inference env-var bindings ----------


def test_from_env_inference_enabled_and_api_key():
    env = {
        "MESHSA_UID": "n1",
        "MESHSA_CALLSIGN": "INF",
        "MESHSA_INFERENCE_ENABLED": "true",
        "MESHSA_INFERENCE_API_KEY": "nvapi-test-key-123",
    }
    c = NodeConfig.from_env(env)
    assert c.inference.enabled is True
    assert c.inference.api_key == "nvapi-test-key-123"
    # defaults preserved for fields not set
    assert c.inference.model == "nvidia/nemotron-3-ultra-550b-a55b"


def test_from_env_inference_all_fields():
    env = {
        "MESHSA_UID": "n2",
        "MESHSA_CALLSIGN": "FULL",
        "MESHSA_INFERENCE_ENABLED": "1",
        "MESHSA_INFERENCE_API_KEY": "key-abc",
        "MESHSA_INFERENCE_BASE_URL": "https://custom.api/v1",
        "MESHSA_INFERENCE_MODEL": "custom/model-7b",
        "MESHSA_INFERENCE_SYSTEM_PROMPT": "Be concise.",
        "MESHSA_INFERENCE_TEMPERATURE": "0.42",
        "MESHSA_INFERENCE_MAX_TOKENS": "256",
        "MESHSA_INFERENCE_TIMEOUT_S": "15.5",
        "MESHSA_INFERENCE_MAX_RETRIES": "5",
    }
    c = NodeConfig.from_env(env)
    assert c.inference.enabled is True
    assert c.inference.api_key == "key-abc"
    assert c.inference.base_url == "https://custom.api/v1"
    assert c.inference.model == "custom/model-7b"
    assert c.inference.system_prompt == "Be concise."
    assert c.inference.temperature == pytest.approx(0.42)
    assert c.inference.max_tokens == 256
    assert c.inference.timeout_s == pytest.approx(15.5)
    assert c.inference.max_retries == 5


@pytest.mark.parametrize(
    "raw,expected",
    [("true", True), ("1", True), ("YES", True), ("0", False), ("false", False), ("no", False)],
)
def test_from_env_inference_enabled_bool_parsing(raw, expected):
    env = {"MESHSA_UID": "n", "MESHSA_CALLSIGN": "B", "MESHSA_INFERENCE_ENABLED": raw}
    c = NodeConfig.from_env(env)
    assert c.inference.enabled is expected


def test_from_env_inference_bad_numeric_names_offending_variable():
    with pytest.raises(ValueError, match="MESHSA_INFERENCE_TEMPERATURE: expected a number"):
        NodeConfig.from_env(
            {"MESHSA_UID": "n", "MESHSA_CALLSIGN": "F", "MESHSA_INFERENCE_TEMPERATURE": "hot"}
        )
    with pytest.raises(ValueError, match="MESHSA_INFERENCE_MAX_TOKENS: expected an integer"):
        NodeConfig.from_env(
            {"MESHSA_UID": "n", "MESHSA_CALLSIGN": "F", "MESHSA_INFERENCE_MAX_TOKENS": "many"}
        )


def test_from_env_inference_json_blob_then_env_var_wins():
    env = {
        "MESHSA_CONFIG_JSON": json.dumps(
            {"uid": "x", "callsign": "OLD", "inference": {"api_key": "blob-key", "max_tokens": 64}}
        ),
        "MESHSA_INFERENCE_API_KEY": "env-key",
    }
    c = NodeConfig.from_env(env)
    assert c.inference.api_key == "env-key"  # env-var wins over blob
    assert c.inference.max_tokens == 64  # blob value retained
