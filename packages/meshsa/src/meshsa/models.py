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
    """A geodetic position; ce/le are circular/linear error in metres."""

    lat: float
    lon: float
    hae: float = 0.0
    ce: float = UNKNOWN_ERROR_M
    le: float = UNKNOWN_ERROR_M

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


class NodeInfo(BaseModel):
    uid: str
    callsign: str
    tier: NodeTier = NodeTier.USER


class PliPayload(BaseModel):
    node: NodeInfo
    position: Position


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
