"""Frozen domain models for the scout pipeline (spec §5).

These mirror the style of :mod:`meshsa.models` (Pydantic, explicit validators,
no operational defaults inline). ``GeoDetection`` is the georeferenced product;
``PixelDetection`` is the pre-projection frame contract — the same JSON shape the
``detection`` codec already speaks, so the jetson pixel ``Detection`` is never
imported (the perception carve-out forbids a meshsa dependency there).
"""

from __future__ import annotations

import math

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: Valid operator triage states for a georeferenced detection.
DETECTION_STATUSES = ("new", "tagged", "rejected", "inspected")


def _finite(name: str, v: float) -> float:
    if not math.isfinite(v):
        raise ValueError(f"{name} must be finite")
    return v


class BBox(BaseModel):
    """Pixel-space bounding box ``(x1, y1)`` top-left, ``(x2, y2)`` bottom-right."""

    model_config = ConfigDict(frozen=True)

    x1: float
    y1: float
    x2: float
    y2: float

    @field_validator("x1", "y1", "x2", "y2")
    @classmethod
    def _is_finite(cls, v: float) -> float:
        return _finite("bbox coord", v)

    @property
    def cx(self) -> float:
        """Horizontal pixel centre."""
        return (self.x1 + self.x2) / 2.0

    @property
    def cy(self) -> float:
        """Vertical pixel centre."""
        return (self.y1 + self.y2) / 2.0


class PixelDetection(BaseModel):
    """A detector output before georeferencing: a class + confidence + pixel box."""

    model_config = ConfigDict(frozen=True)

    frame_id: str
    ts: float
    bbox: BBox
    cls: str
    conf: float

    @field_validator("conf")
    @classmethod
    def _conf_range(cls, v: float) -> float:
        if not math.isfinite(v) or not 0.0 <= v <= 1.0:
            raise ValueError("conf out of range [0, 1]")
        return v

    @field_validator("ts")
    @classmethod
    def _ts_finite(cls, v: float) -> float:
        return _finite("ts", v)


class GeoDetection(BaseModel):
    """A georeferenced, deduplicated anomaly: the grower-facing product.

    ``error_m`` is the ground circular-error estimate (metres). ``status`` is the
    operator triage state; it is immutable here — the store produces an updated
    copy via :meth:`with_status`.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    lat: float
    lon: float
    cls: str
    conf: float
    error_m: float
    src_frame: str
    ts: float
    status: str = "new"
    block_id: str | None = None

    @field_validator("lat")
    @classmethod
    def _lat_range(cls, v: float) -> float:
        if not -90.0 <= v <= 90.0:
            raise ValueError("lat out of range [-90, 90]")
        return v

    @field_validator("lon")
    @classmethod
    def _lon_range(cls, v: float) -> float:
        if not -180.0 <= v <= 180.0:
            raise ValueError("lon out of range [-180, 180]")
        return v

    @field_validator("conf")
    @classmethod
    def _conf_range(cls, v: float) -> float:
        if not math.isfinite(v) or not 0.0 <= v <= 1.0:
            raise ValueError("conf out of range [0, 1]")
        return v

    @field_validator("error_m")
    @classmethod
    def _error_nonneg(cls, v: float) -> float:
        if not math.isfinite(v) or v < 0.0:
            raise ValueError("error_m must be a finite value >= 0")
        return v

    @field_validator("status")
    @classmethod
    def _status_valid(cls, v: str) -> str:
        if v not in DETECTION_STATUSES:
            raise ValueError(f"status must be one of {DETECTION_STATUSES}")
        return v

    def with_status(self, status: str) -> GeoDetection:
        """Return a copy with a new triage ``status``, re-running validation.

        ``model_copy`` skips validators, so we round-trip through ``model_validate`` to
        reject an invalid status rather than silently persisting it.
        """
        return type(self).model_validate({**self.model_dump(), "status": status})


class Block(BaseModel):
    """A vineyard block: boundary polygon + planting geometry (spec §5)."""

    model_config = ConfigDict(frozen=True)

    block_id: str
    #: Boundary as ``(lat, lon)`` vertices; not auto-closed.
    polygon: list[tuple[float, float]]
    row_azimuth_deg: float
    mean_elev_m: float
    vine_spacing_m: float
    row_spacing_m: float

    @field_validator("polygon")
    @classmethod
    def _polygon_valid(cls, v: list[tuple[float, float]]) -> list[tuple[float, float]]:
        if len(v) < 3:
            raise ValueError("polygon needs at least 3 vertices")
        for lat, lon in v:
            if not -90.0 <= lat <= 90.0:
                raise ValueError("polygon lat out of range [-90, 90]")
            if not -180.0 <= lon <= 180.0:
                raise ValueError("polygon lon out of range [-180, 180]")
        return v

    @field_validator("row_azimuth_deg")
    @classmethod
    def _az_range(cls, v: float) -> float:
        if not math.isfinite(v) or not 0.0 <= v < 360.0:
            raise ValueError("row_azimuth_deg out of range [0, 360)")
        return v

    @field_validator("vine_spacing_m", "row_spacing_m")
    @classmethod
    def _spacing_positive(cls, v: float) -> float:
        if not math.isfinite(v) or v <= 0.0:
            raise ValueError("spacing must be a finite value > 0")
        return v


class Waypoint(BaseModel):
    """A single survey waypoint (spec §1 Scout.3)."""

    model_config = ConfigDict(frozen=True)

    seq: int
    lat: float
    lon: float
    alt_agl_m: float = Field(gt=0.0)

    @field_validator("lat")
    @classmethod
    def _lat_range(cls, v: float) -> float:
        if not -90.0 <= v <= 90.0:
            raise ValueError("lat out of range [-90, 90]")
        return v

    @field_validator("lon")
    @classmethod
    def _lon_range(cls, v: float) -> float:
        if not -180.0 <= v <= 180.0:
            raise ValueError("lon out of range [-180, 180]")
        return v
