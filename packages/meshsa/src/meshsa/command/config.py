"""Typed, validated schema for the commander service config (the §4 policy file).

``flightctl/run_commander.py`` used to read the commander JSON as a raw ``dict`` and
pull keys with bare ``cfg["..."]`` / ``int(...)`` / ``float(...)``, so a missing
``audit_path`` was an opaque ``KeyError`` and a typo'd timeout was unbounded. This
mirrors the pydantic ``meshsa.config.NodeConfig`` / ``meshsa.llm.server.ServerConfig``
pattern so the live command surface validates its config once, with clear errors.

Backwards-compat staging (the file is operator-authored and may already be deployed):
  * ``extra="ignore"`` — unknown/legacy keys still load (matches the old raw-dict
    behavior; never fail a running node on an extra key).
  * **coercing** (non-strict) types — ``"3"`` still parses as ``3``.
  * ``mavlink_endpoint`` / ``audit_path`` are **required** (the old code already
    ``KeyError``'d on these — same failure, better message).
  * numeric **bounds warn, they do not reject** this release; the warning says the
    value will be rejected in a future release (see CHANGELOG). This lets a node with
    an out-of-range value still restart while operators are notified.
"""

from __future__ import annotations

from pathlib import Path

import structlog
from pydantic import BaseModel, ConfigDict, Field

from .commands import CommanderSettings

_log = structlog.get_logger("meshsa.command.config")

#: Bounds enforced as warnings now, hard rejections in a future release.
#: (field name, predicate(value) -> ok, human requirement)
_BOUNDS: tuple[tuple[str, str], ...] = (
    ("ack_timeout_s", "must be > 0"),
    ("max_attempts", "must be >= 1"),
    ("arm_report_max_age_s", "must be > 0"),
    ("port", "must be in 1..65535"),
    ("target_system", "must be in 1..255"),
    ("target_component", "must be in 1..255"),
)


class CommanderConfig(BaseModel):
    """Validated commander config; ``to_settings()`` yields the policy dataclass."""

    model_config = ConfigDict(extra="ignore")

    host: str = "127.0.0.1"
    port: int = 8095
    mavlink_endpoint: str
    audit_path: str
    target_system: int = 1
    target_component: int = 1
    allowed: frozenset[str] = Field(default_factory=lambda: frozenset({"set_mode", "rtl"}))
    allow_force_disarm: bool = False
    ack_timeout_s: float = 2.0
    max_attempts: int = 3
    arm_report_max_age_s: float = 2.0

    def model_post_init(self, _ctx: object) -> None:
        """Warn (do not reject, this release) on out-of-range numerics."""
        ok = {
            "ack_timeout_s": self.ack_timeout_s > 0,
            "max_attempts": self.max_attempts >= 1,
            "arm_report_max_age_s": self.arm_report_max_age_s > 0,
            "port": 1 <= self.port <= 65535,
            "target_system": 1 <= self.target_system <= 255,
            "target_component": 1 <= self.target_component <= 255,
        }
        for field_name, requirement in _BOUNDS:
            if not ok[field_name]:
                _log.warning(
                    "commander config value out of range; this will be rejected in a "
                    "future release",
                    field=field_name,
                    value=getattr(self, field_name),
                    requirement=requirement,
                )

    def to_settings(self) -> CommanderSettings:
        """Project the policy subset onto the existing :class:`CommanderSettings`."""
        return CommanderSettings(
            allowed=frozenset(self.allowed),
            allow_force_disarm=self.allow_force_disarm,
            ack_timeout_s=self.ack_timeout_s,
            max_attempts=self.max_attempts,
            arm_report_max_age_s=self.arm_report_max_age_s,
        )

    @classmethod
    def from_file(cls, path: str | Path) -> CommanderConfig:
        """Load + validate the commander JSON config from ``path``."""
        return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))
