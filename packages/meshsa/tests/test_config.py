import json

import pytest
from pydantic import ValidationError

from meshsa import NemotronConfig, NodeConfig, NodeTier


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
        "MESHSA_INFERENCE_BACKOFF_BASE": "1.5",
        "MESHSA_INFERENCE_BACKOFF_MAX_S": "12.0",
        "MESHSA_INFERENCE_INSIGHT_PREFIX": "[AI]",
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
    assert c.inference.backoff_base == pytest.approx(1.5)
    assert c.inference.backoff_max_s == pytest.approx(12.0)
    assert c.inference.insight_prefix == "[AI]"


@pytest.mark.parametrize(
    "raw,expected",
    [("true", True), ("1", True), ("YES", True), ("0", False), ("false", False), ("no", False)],
)
def test_from_env_inference_enabled_bool_parsing(raw, expected):
    env = {"MESHSA_UID": "n", "MESHSA_CALLSIGN": "B", "MESHSA_INFERENCE_ENABLED": raw}
    c = NodeConfig.from_env(env)
    assert c.inference.enabled is expected


# ── Track-B inference config (rate limit / structured / multi-model / offline) ──


def test_from_env_inference_track_b_fields():
    env = {
        "MESHSA_UID": "n2",
        "MESHSA_CALLSIGN": "FULL",
        "MESHSA_INFERENCE_MIN_INTERVAL_S": "0.25",
        "MESHSA_INFERENCE_MAX_CONCURRENT_REQUESTS": "4",
        "MESHSA_INFERENCE_RESPONSE_FORMAT": "json",
        "MESHSA_INFERENCE_GUIDED_JSON_SCHEMA": '{"type": "object"}',
        "MESHSA_INFERENCE_GUIDED_JSON_SUMMARY_FIELD": "report",
        "MESHSA_INFERENCE_MODELS": "nvidia/a, nvidia/b ,nvidia/c",
        "MESHSA_INFERENCE_OFFLINE_QUEUE_MAX": "16",
        # ``model`` must be in the allow-list, else the after-validator rejects it.
        "MESHSA_INFERENCE_MODEL": "nvidia/a",
    }
    c = NodeConfig.from_env(env)
    assert c.inference.min_interval_s == pytest.approx(0.25)
    assert c.inference.max_concurrent_requests == 4
    assert c.inference.response_format == "json"
    assert c.inference.guided_json_schema == '{"type": "object"}'
    assert c.inference.guided_json_summary_field == "report"
    assert c.inference.models == ("nvidia/a", "nvidia/b", "nvidia/c")  # trimmed, order kept
    assert c.inference.offline_queue_max == 16


def test_inference_track_b_defaults_are_no_ops():
    """Unset Track-B fields default to prior behavior (no rate limit / text / no queue)."""
    cfg = NemotronConfig()
    assert cfg.min_interval_s == 0.0
    assert cfg.max_concurrent_requests == 0
    assert cfg.response_format == "text"
    assert cfg.guided_json_schema == ""
    assert cfg.guided_json_summary_field == "summary"
    assert cfg.models == ()
    assert cfg.offline_queue_max == 0


def test_inference_guided_json_schema_valid_object_accepted():
    cfg = NemotronConfig(guided_json_schema='{"type": "object", "properties": {}}')
    assert cfg.guided_json_schema.startswith("{")


def test_inference_guided_json_schema_rejects_malformed_json():
    with pytest.raises(ValidationError, match="not valid JSON"):
        NemotronConfig(guided_json_schema="{not json")


def test_inference_guided_json_schema_rejects_non_object():
    # A JSON array/scalar is valid JSON but not a schema object.
    with pytest.raises(ValidationError, match="must be a JSON object"):
        NemotronConfig(guided_json_schema="[1, 2, 3]")


def test_inference_model_allowlist_rejects_out_of_list_model():
    with pytest.raises(ValidationError):
        NemotronConfig(models=("nvidia/a", "nvidia/b"), model="nvidia/z")


def test_inference_with_model_switches_within_allowlist():
    cfg = NemotronConfig(models=("nvidia/a", "nvidia/b"), model="nvidia/a")
    switched = cfg.with_model("nvidia/b")
    assert switched.model == "nvidia/b"
    assert cfg.model == "nvidia/a"  # original is untouched (copy)


def test_inference_with_model_rejects_out_of_list():
    cfg = NemotronConfig(models=("nvidia/a",), model="nvidia/a")
    with pytest.raises(ValueError, match="allow-list"):
        cfg.with_model("nvidia/z")


def test_inference_with_model_unrestricted_when_no_allowlist():
    cfg = NemotronConfig()  # empty allow-list = no restriction
    assert cfg.with_model("any/model").model == "any/model"


def test_inference_response_format_rejects_unknown_value():
    with pytest.raises(ValidationError):
        NemotronConfig(response_format="xml")


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


def test_from_env_router_overrides():
    """MESHSA_ROUTER_* env vars override RouterConfig defaults."""
    env = {
        "MESHSA_UID": "n1",
        "MESHSA_CALLSIGN": "FOX",
        "MESHSA_ROUTER_DEDUPE_CACHE_SIZE": "4096",
        "MESHSA_ROUTER_QUEUE_MAXSIZE": "500",
    }
    c = NodeConfig.from_env(env)
    assert c.router.dedupe_cache_size == 4096
    assert c.router.queue_maxsize == 500


def test_from_env_health_overrides():
    """MESHSA_HEALTH_* env vars override HealthConfig defaults."""
    env = {
        "MESHSA_UID": "n1",
        "MESHSA_CALLSIGN": "FOX",
        "MESHSA_HEALTH_ENABLED": "true",
        "MESHSA_HEALTH_HOST": "0.0.0.0",
        "MESHSA_HEALTH_PORT": "9090",
        "MESHSA_HEALTH_METRICS_ENABLED": "1",
        "MESHSA_HEALTH_METRICS_PATH": "/stats",
        "MESHSA_HEALTH_METRICS_FORMAT": "json",
    }
    c = NodeConfig.from_env(env)
    assert c.health.enabled is True
    assert c.health.host == "0.0.0.0"
    assert c.health.port == 9090
    assert c.health.metrics_enabled is True
    assert c.health.metrics_path == "/stats"
    assert c.health.metrics_format == "json"


def test_from_env_inference_backoff_base_override():
    """MESHSA_INFERENCE_BACKOFF_BASE env var overrides the default."""
    env = {
        "MESHSA_UID": "n1",
        "MESHSA_CALLSIGN": "FOX",
        "MESHSA_INFERENCE_BACKOFF_BASE": "3.0",
    }
    c = NodeConfig.from_env(env)
    assert c.inference.backoff_base == 3.0


def test_parse_bool_values():
    """Module-level _parse_bool handles all documented truth values."""
    from meshsa.config import _parse_bool

    for truthy in ("true", "True", "TRUE", "1", "yes", "  Yes  "):
        assert _parse_bool("test", truthy) is True, f"Expected True for {truthy!r}"
    for falsy in ("false", "False", "0", "no", ""):
        assert _parse_bool("test", falsy) is False, f"Expected False for {falsy!r}"
    with pytest.raises(ValueError, match="test: expected a boolean"):
        _parse_bool("test", "nope")
    with pytest.raises(ValueError, match="test: expected a boolean"):
        _parse_bool("test", "invalid")


def test_from_env_router_bad_numeric():
    """MESHSA_ROUTER_* env vars with non-numeric values raise ValueError."""
    with pytest.raises(ValueError, match="MESHSA_ROUTER_DEDUPE_CACHE_SIZE: expected an integer"):
        NodeConfig.from_env(
            {"MESHSA_UID": "n", "MESHSA_CALLSIGN": "F", "MESHSA_ROUTER_DEDUPE_CACHE_SIZE": "big"}
        )


def test_from_env_health_bad_port():
    """MESHSA_HEALTH_PORT with non-integer value raises ValueError."""
    with pytest.raises(ValueError, match="MESHSA_HEALTH_PORT: expected an integer"):
        NodeConfig.from_env(
            {"MESHSA_UID": "n", "MESHSA_CALLSIGN": "F", "MESHSA_HEALTH_PORT": "eighty"}
        )


# ---------- required-field validation ----------


def test_missing_uid_raises():
    """NodeConfig without uid must raise a Pydantic ValidationError."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="uid"):
        NodeConfig(callsign="ALPHA")  # type: ignore[call-arg]


def test_missing_callsign_raises():
    """NodeConfig without callsign must raise a Pydantic ValidationError."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="callsign"):
        NodeConfig(uid="u1")  # type: ignore[call-arg]


def test_from_file_nonexistent_raises(tmp_path):
    """from_file with a path that does not exist must raise FileNotFoundError."""
    missing = str(tmp_path / "does_not_exist.json")
    with pytest.raises(FileNotFoundError):
        NodeConfig.from_file(missing)


def test_nemotron_config_constraints():
    from pydantic import ValidationError

    from meshsa.config import NemotronConfig

    # backoff_base < 1.0 raises ValidationError
    with pytest.raises(ValidationError, match="backoff_base"):
        NemotronConfig(backoff_base=0.9)

    # insight_prefix empty raises ValidationError
    with pytest.raises(ValidationError, match="insight_prefix"):
        NemotronConfig(insight_prefix="")
