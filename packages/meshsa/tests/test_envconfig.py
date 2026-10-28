"""Unit tests for ``meshsa._envconfig`` — the declarative env loader (design D-11)."""

from __future__ import annotations

import enum
from typing import Literal

import pytest
from pydantic import BaseModel

from meshsa._envconfig import (
    apply_overrides,
    caster_for,
    env_inventory,
    env_key,
    env_scalar,
    load_sections,
    merge_config_json,
    parse_bool,
    parse_csv,
    parse_str,
    parse_token,
)
from meshsa._parsing import parse_float, parse_int


class _Tier(str, enum.Enum):
    A = "a"
    B = "b"


class _Inner(BaseModel):
    flag: bool = False
    count: int = 1
    ratio: float = 0.5
    name: str = "x"
    maybe: str | None = None
    maybe_int: int | None = None
    mode: Literal["fast", "slow"] = "fast"
    tier: _Tier = _Tier.A
    items: tuple[str, ...] = ()
    names: frozenset[str] = frozenset()


class _Outer(BaseModel):
    uid: str = "u"
    inner: _Inner = _Inner()
    things: list[str] = []
    table: dict[str, int] = {}


# ── casters ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("raw", ["true", "1", "yes", " TRUE ", "Yes"])
def test_parse_bool_truthy(raw: str) -> None:
    assert parse_bool("K", raw) is True


@pytest.mark.parametrize("raw", ["false", "0", "no", "", "  No "])
def test_parse_bool_falsy(raw: str) -> None:
    assert parse_bool("K", raw) is False


def test_parse_bool_rejects_and_names_the_key() -> None:
    with pytest.raises(ValueError, match="MESHSA_X: expected a boolean, got 'ture'"):
        parse_bool("MESHSA_X", "ture")


def test_parse_csv_trims_and_drops_empties() -> None:
    assert parse_csv("K", " a, b ,,c,") == ("a", "b", "c")
    assert parse_csv("K", "") == ()


def test_parse_token_normalises() -> None:
    assert parse_token("K", "  tok \n") == "tok"
    assert parse_token("K", "") is None
    assert parse_token("K", "   ") is None


def test_parse_str_is_identity() -> None:
    assert parse_str("K", " raw ") == " raw "


@pytest.mark.parametrize(
    "field, caster",
    [
        ("flag", parse_bool),
        ("count", parse_int),
        ("ratio", parse_float),
        ("name", parse_str),
        ("maybe", parse_str),
        ("maybe_int", parse_int),
        ("mode", parse_str),
        ("tier", parse_str),
        ("items", parse_csv),
        ("names", parse_csv),
    ],
)
def test_caster_for_derives_from_the_annotation(field: str, caster: object) -> None:
    assert caster_for(_Inner, field) is caster


@pytest.mark.parametrize("field", ["inner", "things", "table"])
def test_caster_for_refuses_structured_fields(field: str) -> None:
    with pytest.raises(TypeError, match=f"_Outer.{field}"):
        caster_for(_Outer, field)


# ── keys ──────────────────────────────────────────────────────────────────────


def test_env_key_is_mechanical() -> None:
    assert env_key("MESHSA_", None, "uid") == "MESHSA_UID"
    assert env_key("MESHSA_", "health", "metrics_path") == "MESHSA_HEALTH_METRICS_PATH"
    assert env_key("X_", "ui", "port") == "X_UI_PORT"


# ── apply_overrides ───────────────────────────────────────────────────────────


def test_apply_overrides_binds_every_field_by_default() -> None:
    env = {
        "P_INNER_FLAG": "yes",
        "P_INNER_COUNT": "7",
        "P_INNER_RATIO": "0.25",
        "P_INNER_NAME": "n",
        "P_INNER_MAYBE": "m",
        "P_INNER_MAYBE_INT": "3",
        "P_INNER_MODE": "slow",
        "P_INNER_TIER": "b",
        "P_INNER_ITEMS": "a,b",
        "P_INNER_NAMES": "c, d",
        "P_INNER_UNKNOWN": "ignored",
    }
    data = apply_overrides(_Inner, {"name": "blob"}, env, prefix="P_", section="inner")
    assert data == {
        "flag": True,
        "count": 7,
        "ratio": 0.25,
        "name": "n",
        "maybe": "m",
        "maybe_int": 3,
        "mode": "slow",
        "tier": "b",
        "items": ("a", "b"),
        "names": ("c", "d"),
    }
    inner = _Inner.model_validate(data)
    assert inner.tier is _Tier.B
    assert inner.names == frozenset({"c", "d"})


def test_apply_overrides_leaves_absent_keys_alone_and_applies_empty_values() -> None:
    data = apply_overrides(_Inner, {"count": 9}, {"P_NAME": ""}, prefix="P_")
    assert data == {"count": 9, "name": ""}  # present-but-empty is applied; absent untouched


def test_apply_overrides_fields_limits_the_bindable_set() -> None:
    env = {"P_UID": "x", "P_INNER": "nope"}
    assert apply_overrides(_Outer, {}, env, prefix="P_", fields=("uid",)) == {"uid": "x"}
    # Without the limit, the structured field would be reached and refused:
    with pytest.raises(TypeError):
        apply_overrides(_Outer, {}, {"P_INNER": "nope"}, prefix="P_")


def test_apply_overrides_aliases_and_casters_override_the_derivation() -> None:
    def bounded(name: str, raw: str) -> int:
        return parse_int(name, raw, lo=1, hi=10)

    env = {"ABS_COUNT": "5", "P_RATIO": "1.5"}
    data = apply_overrides(
        _Inner,
        {},
        env,
        prefix="P_",
        fields=("count", "ratio"),
        aliases={"count": "ABS_COUNT"},
        casters={"count": bounded},
    )
    assert data == {"count": 5, "ratio": 1.5}
    with pytest.raises(ValueError, match="ABS_COUNT: 50 is above the maximum 10"):
        apply_overrides(
            _Inner,
            {},
            {"ABS_COUNT": "50"},
            prefix="P_",
            aliases={"count": "ABS_COUNT"},
            casters={"count": bounded},
        )


def test_apply_overrides_errors_name_the_env_key() -> None:
    with pytest.raises(ValueError, match="P_INNER_COUNT: expected an integer, got 'many'"):
        apply_overrides(_Inner, {}, {"P_INNER_COUNT": "many"}, prefix="P_", section="inner")
    with pytest.raises(ValueError, match="P_INNER_RATIO: expected a number"):
        apply_overrides(_Inner, {}, {"P_INNER_RATIO": "nan-ish"}, prefix="P_", section="inner")


# ── load_sections / merge_config_json ────────────────────────────────────────


def test_load_sections_overlays_blob_sections_and_skips_untouched_ones() -> None:
    data = {"inner": {"name": "blob", "count": 2}}
    env = {"P_INNER_COUNT": "3", "P_OTHER_FLAG": "true"}
    out = load_sections(data, env, prefix="P_", sections={"inner": _Inner, "other": _Inner})
    assert out == {"inner": {"name": "blob", "count": 3}, "other": {"flag": True}}
    assert load_sections({}, {}, prefix="P_", sections={"inner": _Inner}) == {}


def test_merge_config_json_merges_then_scalars_win() -> None:
    env = {"P_CONFIG_JSON": '{"uid": "blob", "inner": {"count": 4}}', "P_UID": "scalar"}
    data = merge_config_json({}, env, prefix="P_")
    assert data == {"uid": "blob", "inner": {"count": 4}}
    apply_overrides(_Outer, data, env, prefix="P_", fields=("uid",))
    assert data["uid"] == "scalar"
    assert merge_config_json({"a": 1}, {"P_CONFIG_JSON": ""}, prefix="P_") == {"a": 1}


def test_merge_config_json_bad_blob_raises() -> None:
    with pytest.raises(ValueError):
        merge_config_json({}, {"P_CONFIG_JSON": "{not json"}, prefix="P_")


# ── inventory / env_scalar ────────────────────────────────────────────────────


def test_env_inventory_lists_every_derived_key_in_order() -> None:
    keys = env_inventory(
        "P_",
        top_level=("uid", "drone"),
        sections={"inner": _Inner},
        aliases={"drone": "ABS_DRONE"},
    )
    assert keys[:3] == ["P_CONFIG_JSON", "P_UID", "ABS_DRONE"]
    assert keys[3:] == [f"P_INNER_{name.upper()}" for name in _Inner.model_fields]
    assert len(keys) == 3 + len(_Inner.model_fields)


def test_env_scalar_default_or_cast() -> None:
    assert env_scalar({}, "K", 5, parse_int) == 5
    assert env_scalar({"K": "7"}, "K", 5, parse_int) == 7
    assert env_scalar({"K": "x"}, "K", "d") == "x"
    with pytest.raises(ValueError, match="K: expected an integer"):
        env_scalar({"K": "x"}, "K", 5, parse_int)
