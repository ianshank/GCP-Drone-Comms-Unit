"""Pydantic data models. Operational defaults live in :mod:`meshsa.config`,
never inline here, so behaviour is configuration-driven."""

from __future__ import annotations

import enum
from typing import Any

from pydantic import BaseModel, Field, field_validator

from .version import SCHEMA_VERSION

#: CoT/TAK "unknown / very large" sentinel for circular/linear error (metres).
#: Shared so models and the CoT codec agree on a single value.
UNKNOWN_ERROR_M = 9_999_999.0


class NodeTier(str, enum.Enum):
    USER = "user"
    BACKBONE = "backbone"
    BASE = "base"


class MessageKind(str, enum.Enum):
    PLI = "pli"
    CHAT = "chat"
    MARKER = "marker"
    STATUS = "status"


class Position(BaseModel):
    """A geodetic position; ce/le are circular/linear error in metres.

    ``course_deg``/``speed_ms`` are OPTIONAL richer-track fields (default ``None``);
    when absent they must be dropped from the wire via ``model_dump(exclude_none=True)``
    so old readers see byte-identical payloads.
    """

    lat: float
    lon: float
    hae: float = 0.0
    ce: float = UNKNOWN_ERROR_M
    le: float = UNKNOWN_ERROR_M
    course_deg: float | None = None
    speed_ms: float | None = None

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

    @field_validator("course_deg")
    @classmethod
    def _course_range(cls, v: float | None) -> float | None:
        if v is not None and not 0.0 <= v < 360.0:
            raise ValueError("course_deg out of range [0, 360)")
        return v

    @field_validator("speed_ms")
    @classmethod
    def _speed_nonneg(cls, v: float | None) -> float | None:
        if v is not None and v < 0.0:
            raise ValueError("speed_ms must be >= 0")
        return v


class Attitude(BaseModel):
    """Optional aircraft attitude (degrees); all fields default ``None``."""

    roll_deg: float | None = None
    pitch_deg: float | None = None
    yaw_deg: float | None = None


class Telemetry(BaseModel):
    """Optional vehicle telemetry block; all fields default ``None`` so an absent
    block is dropped from the wire via ``model_dump(exclude_none=True)``."""

    battery_v: float | None = None
    battery_pct: int | None = None
    current_a: float | None = None
    attitude: Attitude | None = None

    @field_validator("battery_v")
    @classmethod
    def _battery_v_nonneg(cls, v: float | None) -> float | None:
        if v is not None and v < 0.0:
            raise ValueError("battery_v must be >= 0")
        return v

    @field_validator("battery_pct")
    @classmethod
    def _battery_pct_range(cls, v: int | None) -> int | None:
        if v is not None and not 0 <= v <= 100:
            raise ValueError("battery_pct out of range [0, 100]")
        return v


class NodeInfo(BaseModel):
    uid: str
    callsign: str
    tier: NodeTier = NodeTier.USER


class PliPayload(BaseModel):
    node: NodeInfo
    position: Position
    telemetry: Telemetry | None = None


class ChatPayload(BaseModel):
    text: str
    to: str | None = None


class Envelope(BaseModel):
    """Versioned wire envelope carried by every transport."""

    schema_version: int = Field(default=SCHEMA_VERSION)
    msg_id: str
    ts: float
    source_uid: str
    kind: MessageKind
    payload: dict[str, Any] = Field(default_factory=dict)
