"""``meshsa-scout`` command line: replay, gen-mission, run-station, --health-check (spec §1).

``run`` is a pure-ish dispatcher (returns an exit code) so the subcommands are unit-testable
without a process boundary; ``main`` is the console entry point. The ``--health-check`` runs the
replay pipeline end-to-end and asserts known ground-truth anomalies geolocate within the RTK
error budget and dedupe to the expected pin count — the software "definition of done".
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

import structlog

from ..config import ScoutConfig
from ..cv.geo import Camera, ground_distance_m
from .pipeline import ScoutPipeline
from .replay import DEFAULT_CAMERA, ReplayFlight
from .schemas import Block
from .store import to_geojson
from .survey import plan_boustrophedon
from .terrain import FlatTerrain

_log = structlog.get_logger("meshsa.scout.cli")

#: Health-check acceptance: max geolocation error (m) for a known truth under RTK noise.
_HEALTH_BUDGET_M = 3.0


def sample_block() -> Block:
    """A small synthetic block used by ``replay`` / ``--health-check`` (no data files)."""
    return Block(
        block_id="sample",
        polygon=[
            (38.5000, -122.5000),
            (38.5000, -122.4980),
            (38.5015, -122.4980),
            (38.5015, -122.5000),
        ],
        row_azimuth_deg=0.0,
        mean_elev_m=60.0,
        vine_spacing_m=2.0,
        row_spacing_m=2.4,
    )


def load_block(path: str) -> Block:
    """Load a :class:`Block` from a JSON file matching the model fields."""
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    data["polygon"] = [tuple(p) for p in data["polygon"]]
    return Block.model_validate(data)


def _run_replay(
    block: Block, config: ScoutConfig, *, rtk: bool, seed: int
) -> tuple[ScoutPipeline, ReplayFlight]:
    flight = ReplayFlight(
        block,
        camera=DEFAULT_CAMERA,
        alt_agl_m=config.survey_alt_agl_m,
        forward_overlap=config.forward_overlap,
        side_overlap=config.side_overlap,
        rtk_enabled=rtk,
        seed=seed,
    )
    pipe = ScoutPipeline(
        camera=flight.camera,
        terrain=FlatTerrain(block.mean_elev_m),
        params=config,
        block_id=block.block_id,
    )
    pipe.ingest(flight.poses, flight.detections)
    return pipe, flight


def _health_check(config: ScoutConfig) -> int:
    block = sample_block()
    pipe, flight = _run_replay(block, config, rtk=True, seed=1)
    pins = pipe.store.all()
    truths = flight.ground_truths
    if len(pins) != len(truths):
        _log.error("health_check_pin_count", pins=len(pins), truths=len(truths))
        return 1
    worst = 0.0
    for gt in truths:
        nearest = min(ground_distance_m(gt.lat, gt.lon, p.lat, p.lon) for p in pins)
        worst = max(worst, nearest)
        if nearest > _HEALTH_BUDGET_M:
            _log.error("health_check_error_budget", error_m=nearest, budget_m=_HEALTH_BUDGET_M)
            return 1
    _log.info(
        "health_check_ok",
        pins=len(pins),
        truths=len(truths),
        worst_error_m=round(worst, 3),
        budget_m=_HEALTH_BUDGET_M,
    )
    print(
        f"scout health-check OK: {len(pins)} pins, worst error {worst:.2f} m (budget {_HEALTH_BUDGET_M} m)"
    )
    return 0


def _cmd_replay(args: argparse.Namespace, config: ScoutConfig) -> int:
    block = load_block(args.block) if args.block else sample_block()
    pipe, _flight = _run_replay(block, config, rtk=not args.no_rtk, seed=args.seed)
    print(json.dumps(to_geojson(pipe.store.all())))
    return 0


def _cmd_gen_mission(args: argparse.Namespace, config: ScoutConfig) -> int:
    from .export_mission import to_ardupilot_waypoints, to_qgc_plan

    block = load_block(args.block) if args.block else sample_block()
    camera: Camera = DEFAULT_CAMERA
    waypoints = plan_boustrophedon(
        block,
        h_fov_deg=camera.h_fov_deg,
        v_fov_deg=camera.v_fov_deg,
        alt_agl_m=config.survey_alt_agl_m,
        side_overlap=config.side_overlap,
    )
    if args.out_plan:
        plan = to_qgc_plan(
            waypoints,
            cruise_speed_ms=config.survey_cruise_speed_ms,
            hover_speed_ms=config.survey_hover_speed_ms,
        )
        with open(args.out_plan, "w", encoding="utf-8") as fh:
            json.dump(plan, fh, indent=2)
    if args.out_waypoints:
        with open(args.out_waypoints, "w", encoding="utf-8") as fh:
            fh.write(to_ardupilot_waypoints(waypoints))
    print(f"generated {len(waypoints)} waypoints for block {block.block_id!r}")
    return 0


def _cmd_run_station(
    args: argparse.Namespace, config: ScoutConfig
) -> int:  # pragma: no cover - serve loop
    from aiohttp import web

    from .station import build_app, validate_bind

    block = load_block(args.block) if args.block else sample_block()
    pipe, _flight = _run_replay(block, config, rtk=not args.no_rtk, seed=args.seed)
    token = config.station_token or None
    validate_bind(config.station_host, token)
    app = build_app(pipe.store, token=token)
    web.run_app(app, host=config.station_host, port=config.station_port)
    return 0


def run(argv: Sequence[str]) -> int:
    """Dispatch a scout CLI invocation; return a process exit code."""
    parser = argparse.ArgumentParser(prog="meshsa-scout", description="Vineyard scouting tools.")
    parser.add_argument(
        "--health-check", action="store_true", help="run the replay pipeline and self-check"
    )
    sub = parser.add_subparsers(dest="command")

    p_replay = sub.add_parser(
        "replay", help="run a synthetic survey and print detections as GeoJSON"
    )
    p_replay.add_argument("--block", help="path to a block JSON file (default: built-in sample)")
    p_replay.add_argument("--seed", type=int, default=0)
    p_replay.add_argument(
        "--no-rtk", action="store_true", help="use M8N-level noise instead of RTK"
    )

    p_mission = sub.add_parser(
        "gen-mission", help="generate a QGC .plan / ArduPilot .waypoints survey"
    )
    p_mission.add_argument("--block", help="path to a block JSON file (default: built-in sample)")
    p_mission.add_argument("--out-plan", help="write a QGC .plan to this path")
    p_mission.add_argument("--out-waypoints", help="write an ArduPilot .waypoints to this path")

    p_station = sub.add_parser("run-station", help="serve the aiohttp+MapLibre operator view")
    p_station.add_argument("--block", help="path to a block JSON file (default: built-in sample)")
    p_station.add_argument("--seed", type=int, default=0)
    p_station.add_argument("--no-rtk", action="store_true")

    args = parser.parse_args(argv)
    # Scout tunables: defaults here; a node/gateway resolves MESHSA_SCOUT_* via NodeConfig.
    config = ScoutConfig()

    if args.health_check:
        return _health_check(config)
    if args.command == "replay":
        return _cmd_replay(args, config)
    if args.command == "gen-mission":
        return _cmd_gen_mission(args, config)
    if args.command == "run-station":
        return _cmd_run_station(args, config)
    parser.print_help()
    return 1


def main() -> None:  # pragma: no cover - process entry point
    """Console entry point (``meshsa-scout``)."""
    raise SystemExit(run(sys.argv[1:]))
