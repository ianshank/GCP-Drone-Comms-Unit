"""meshsa.scout — vineyard structural-anomaly scouting.

Turns a mapping survey flight (RGB detections + autopilot pose) into a
georeferenced, deduplicated map of structural anomalies, rendered on the
existing TAK/CoT path and an optional thin web view.

Spec: docs/specs/initiative-scout.md. Every operational value is a
:class:`meshsa.config.ScoutConfig` field (no magic numbers); all I/O is behind
``Protocol`` seams so tests need no hardware.
"""

from __future__ import annotations

from .dedup import Deduplicator
from .pipeline import ScoutPipeline, make_marker_codec
from .pose import PoseFuser
from .protocols import DetectionSource, PoseSource, Store, Terrain
from .schemas import BBox, Block, GeoDetection, PixelDetection, Waypoint
from .store import InMemoryStore, SqliteStore, build_store, to_csv, to_geojson
from .sync import TimeSync
from .terrain import FlatTerrain, GriddedTerrain, build_terrain, grid_from_band, load_dem

__all__ = [
    "BBox",
    "Block",
    "GeoDetection",
    "PixelDetection",
    "Waypoint",
    "PoseSource",
    "DetectionSource",
    "Terrain",
    "Store",
    "FlatTerrain",
    "GriddedTerrain",
    "build_terrain",
    "grid_from_band",
    "load_dem",
    "PoseFuser",
    "TimeSync",
    "Deduplicator",
    "ScoutPipeline",
    "make_marker_codec",
    "InMemoryStore",
    "SqliteStore",
    "build_store",
    "to_geojson",
    "to_csv",
]
