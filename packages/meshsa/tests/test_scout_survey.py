"""Tests for meshsa.scout.survey + export_mission — coverage + file formats."""

from __future__ import annotations

import pytest

from meshsa.scout.cli import sample_block
from meshsa.scout.export_mission import to_ardupilot_waypoints, to_qgc_plan
from meshsa.scout.replay import DEFAULT_CAMERA
from meshsa.scout.survey import coverage_fraction, plan_boustrophedon


def _plan(side_overlap: float = 0.65):
    block = sample_block()
    return block, plan_boustrophedon(
        block,
        h_fov_deg=DEFAULT_CAMERA.h_fov_deg,
        v_fov_deg=DEFAULT_CAMERA.v_fov_deg,
        alt_agl_m=60.0,
        side_overlap=side_overlap,
    )


def test_path_covers_block_fully() -> None:
    block, path = _plan(side_overlap=0.65)
    assert len(path) >= 2
    assert len(path) % 2 == 0  # two turn points per transect
    frac = coverage_fraction(
        block,
        path,
        h_fov_deg=DEFAULT_CAMERA.h_fov_deg,
        v_fov_deg=DEFAULT_CAMERA.v_fov_deg,
        alt_agl_m=60.0,
    )
    assert frac == pytest.approx(1.0, abs=0.02)


def test_waypoints_carry_altitude() -> None:
    _block, path = _plan()
    assert all(w.alt_agl_m == 60.0 for w in path)
    assert [w.seq for w in path] == list(range(len(path)))


def test_invalid_side_overlap_rejected() -> None:
    block = sample_block()
    with pytest.raises(ValueError):
        plan_boustrophedon(block, h_fov_deg=70, v_fov_deg=42, alt_agl_m=60, side_overlap=1.0)


def test_coverage_empty_path_is_zero() -> None:
    block = sample_block()
    assert coverage_fraction(block, [], h_fov_deg=70, v_fov_deg=42, alt_agl_m=60) == 0.0


def test_coverage_sparse_path_is_partial() -> None:
    # A single transect (first two waypoints of a full plan) covers only its own swath band,
    # not the whole block -> a fraction strictly between 0 and 1.
    block, full = _plan(side_overlap=0.65)
    one_transect = full[:2]
    frac = coverage_fraction(
        block,
        one_transect,
        h_fov_deg=DEFAULT_CAMERA.h_fov_deg,
        v_fov_deg=DEFAULT_CAMERA.v_fov_deg,
        alt_agl_m=60.0,
    )
    assert 0.0 < frac < 1.0


def test_qgc_plan_structure() -> None:
    _block, path = _plan()
    plan = to_qgc_plan(path)
    assert plan["fileType"] == "Plan"
    mission = plan["mission"]
    assert isinstance(mission, dict)
    assert len(mission["items"]) == len(path)
    assert mission["items"][0]["command"] == 16  # NAV_WAYPOINT
    assert len(mission["plannedHomePosition"]) == 3


def test_qgc_plan_empty_home_default() -> None:
    plan = to_qgc_plan([])
    assert plan["mission"]["plannedHomePosition"] == [0.0, 0.0, 0.0]  # type: ignore[index]


def test_ardupilot_waypoints_format() -> None:
    _block, path = _plan()
    text = to_ardupilot_waypoints(path)
    lines = text.strip().splitlines()
    assert lines[0] == "QGC WPL 110"
    assert len(lines) == len(path) + 1
    cols = lines[1].split("\t")
    assert cols[0] == "0"  # seq
    assert cols[1] == "1"  # first row is current
    assert cols[3] == "16"  # NAV_WAYPOINT
    assert cols[-1] == "1"  # autocontinue
