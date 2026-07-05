"""Tests for the meshsa-scout CLI dispatcher."""

from __future__ import annotations

import json
from pathlib import Path

from meshsa.scout.cli import load_block, run, sample_block


def test_sample_block_valid() -> None:
    block = sample_block()
    assert block.block_id == "sample"
    assert len(block.polygon) == 4


def test_health_check_exits_zero(capsys) -> None:  # type: ignore[no-untyped-def]
    assert run(["--health-check"]) == 0
    assert "health-check OK" in capsys.readouterr().out


def test_replay_prints_geojson(capsys) -> None:  # type: ignore[no-untyped-def]
    assert run(["replay", "--seed", "1"]) == 0
    # Structured logs and the GeoJSON share stdout; the JSON document is the final line.
    fc = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert fc["type"] == "FeatureCollection"
    assert len(fc["features"]) == 3


def test_replay_no_rtk(capsys) -> None:  # type: ignore[no-untyped-def]
    assert run(["replay", "--no-rtk", "--seed", "1"]) == 0
    capsys.readouterr()


def test_gen_mission_writes_files(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    plan = tmp_path / "survey.plan"
    wp = tmp_path / "survey.waypoints"
    assert run(["gen-mission", "--out-plan", str(plan), "--out-waypoints", str(wp)]) == 0
    assert json.loads(plan.read_text())["fileType"] == "Plan"
    assert wp.read_text().startswith("QGC WPL 110")
    assert "generated" in capsys.readouterr().out


def test_load_block_roundtrip(tmp_path: Path) -> None:
    block = sample_block()
    path = tmp_path / "block.json"
    path.write_text(
        json.dumps(
            {
                "block_id": block.block_id,
                "polygon": [list(p) for p in block.polygon],
                "row_azimuth_deg": block.row_azimuth_deg,
                "mean_elev_m": block.mean_elev_m,
                "vine_spacing_m": block.vine_spacing_m,
                "row_spacing_m": block.row_spacing_m,
            }
        )
    )
    loaded = load_block(str(path))
    assert loaded.block_id == block.block_id
    assert loaded.polygon == block.polygon


def test_replay_with_block_file(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "block.json"
    b = sample_block()
    path.write_text(
        json.dumps(
            {
                "block_id": b.block_id,
                "polygon": [list(p) for p in b.polygon],
                "row_azimuth_deg": b.row_azimuth_deg,
                "mean_elev_m": b.mean_elev_m,
                "vine_spacing_m": b.vine_spacing_m,
                "row_spacing_m": b.row_spacing_m,
            }
        )
    )
    assert run(["replay", "--block", str(path)]) == 0
    capsys.readouterr()


def test_no_command_prints_help(capsys) -> None:  # type: ignore[no-untyped-def]
    assert run([]) == 1
    assert "meshsa-scout" in capsys.readouterr().out
