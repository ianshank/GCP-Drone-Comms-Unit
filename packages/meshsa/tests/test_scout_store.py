"""Tests for meshsa.scout.store — in-memory + sqlite stores and exporters."""

from __future__ import annotations

import json

import pytest

from meshsa.scout.protocols import Store
from meshsa.scout.schemas import GeoDetection
from meshsa.scout.store import InMemoryStore, SqliteStore, to_csv, to_geojson


def _det(id_: str, block: str | None = "b1") -> GeoDetection:
    return GeoDetection(
        id=id_,
        lat=38.5,
        lon=-122.5,
        cls="missing_vine",
        conf=0.9,
        error_m=0.4,
        src_frame="f",
        ts=1.0,
        block_id=block,
    )


def _exercise_store(store: Store) -> None:
    store.add(_det("a"))
    store.add(_det("b", block="b2"))
    assert store.get("a") is not None
    assert store.get("missing") is None
    assert len(store.all()) == 2
    assert [d.id for d in store.by_block("b1")] == ["a"]
    updated = store.set_status("a", "tagged")
    assert updated is not None and updated.status == "tagged"
    assert store.get("a").status == "tagged"  # type: ignore[union-attr]
    assert store.set_status("missing", "tagged") is None


def test_in_memory_store() -> None:
    _exercise_store(InMemoryStore())


def test_sqlite_store_roundtrip() -> None:
    store = SqliteStore(":memory:")
    _exercise_store(store)
    # Re-read to prove persistence through the SQL layer, not just an in-process dict.
    assert store.get("b").block_id == "b2"  # type: ignore[union-attr]
    store.close()


def test_sqlite_invalid_status_rejected() -> None:
    store = SqliteStore(":memory:")
    store.add(_det("a"))
    with pytest.raises(ValueError):
        store.set_status("a", "bogus")
    store.close()


def test_to_geojson_structure() -> None:
    fc = to_geojson([_det("a")])
    assert fc["type"] == "FeatureCollection"
    feats = fc["features"]
    assert isinstance(feats, list)
    feat = feats[0]
    assert feat["geometry"]["coordinates"] == [-122.5, 38.5]  # lon, lat
    assert feat["properties"]["cls"] == "missing_vine"
    # Round-trips through JSON.
    assert json.loads(json.dumps(fc))["features"][0]["properties"]["id"] == "a"


def test_to_csv_header_and_rows() -> None:
    csv_text = to_csv([_det("a"), _det("b")])
    lines = csv_text.strip().splitlines()
    assert lines[0].split(",")[0] == "id"
    assert len(lines) == 3  # header + 2 rows
    assert lines[1].startswith("a,")
