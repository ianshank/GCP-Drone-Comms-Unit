"""Operator-console configuration (spec §5.1).

Every operational value — cadence, TTL, cap, port, URL — is a field with an explicit
default and a ``MESHSA_UI_*`` env binding (wired in :meth:`meshsa.config.NodeConfig.from_env`),
per CHARTER §4.5: no magic numbers. Defaults open **zero** new surface: ``enabled=false``,
loopback bind, no token.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .logring import VALID_LEVELS

#: Default bind port; unclaimed in the docs/AUDIT_M2_AUTH.md inventory (and deliberately
#: clear of the known scout-station / detection-ingest 8099 double-booking).
DEFAULT_UI_PORT = 8100


class UIConfig(BaseModel):
    """Operator-console tunables (``meshsa.ui``; spec §5.1).

    ``token=None`` (the default) keeps the loopback-only, no-auth posture; a non-loopback
    ``host`` without a token is refused fail-closed by ``meshsa.ui.app.validate_bind``.
    An empty/whitespace token normalises to ``None`` — an empty credential is no credential
    (mirrors ``meshsa.llm.server.resolve_config``).
    """

    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = Field(default=DEFAULT_UI_PORT, gt=0, lt=65536)
    token: str | None = None
    map_style_url: str = "https://demotiles.maplibre.org/style.json"
    poll_interval_s: float = Field(default=2.0, gt=0.0)
    track_stale_s: float = Field(default=300.0, gt=0.0)
    detection_stale_s: float = Field(default=3600.0, gt=0.0)
    max_tracks: int = Field(default=256, gt=0)
    max_detections: int = Field(default=1024, gt=0)
    chat_enabled: bool = False
    log_ring_enabled: bool = False
    log_ring_size: int = Field(default=200, gt=0)
    log_ring_level: str = "info"
    metrics_format: Literal["prometheus", "json"] = "json"
    title: str = "MeshSA Operator"

    @field_validator("token")
    @classmethod
    def _empty_token_is_none(cls, v: str | None) -> str | None:
        """``""``/whitespace -> ``None``: an empty credential is no credential."""
        if v is None:
            return None
        stripped = v.strip()
        return stripped or None

    @field_validator("log_ring_level")
    @classmethod
    def _known_log_level(cls, v: str) -> str:
        """Fail at config parse, not at wiring: ``LogRing`` accepts only these levels."""
        normalized = v.strip().lower()
        if normalized not in VALID_LEVELS:
            raise ValueError(f"unknown log level {v!r}; expected one of {sorted(VALID_LEVELS)}")
        return normalized
