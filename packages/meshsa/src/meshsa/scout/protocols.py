"""Structural seams for the scout pipeline (spec §3).

All I/O is injected through these ``Protocol`` types so the pipeline can be
assembled with synthetic replay sources and fakes in tests — no radios, GPS,
camera, or autopilot. ``Terrain`` and ``Pose`` are defined in the lower
:mod:`meshsa.cv.geo` layer and re-exported here so scout has one import surface.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from ..cv.geo import Pose, Terrain
from .pose import FusedPose
from .schemas import GeoDetection, PixelDetection

__all__ = [
    "Pose",
    "FusedPose",
    "Terrain",
    "PoseSource",
    "DetectionSource",
    "Store",
]


@runtime_checkable
class PoseSource(Protocol):
    """Yields projector-ready :class:`~meshsa.scout.pose.FusedPose` samples.

    A fused pose carries position + AGL + heading/depression + camera roll + timestamp
    (replay, or MAVLink position+``ATTITUDE`` fused via :class:`~meshsa.scout.pose.PoseFuser`).
    """

    def stream(self) -> AsyncIterator[FusedPose]: ...


@runtime_checkable
class DetectionSource(Protocol):
    """Yields :class:`~meshsa.scout.schemas.PixelDetection` frames (replay or IMX500)."""

    def stream(self) -> AsyncIterator[PixelDetection]: ...


@runtime_checkable
class Store(Protocol):
    """Persists georeferenced detections, scoped per block/session."""

    def add(self, detection: GeoDetection) -> None: ...

    def get(self, detection_id: str) -> GeoDetection | None: ...

    def all(self) -> list[GeoDetection]: ...

    def by_block(self, block_id: str) -> list[GeoDetection]: ...

    def set_status(self, detection_id: str, status: str) -> GeoDetection | None: ...
