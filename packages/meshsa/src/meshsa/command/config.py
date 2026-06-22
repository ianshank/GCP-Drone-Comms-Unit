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

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import structlog
from pydantic import BaseModel, ConfigDict, Field

from .._parsing import parse_float, parse_int
from ..config import _parse_bool
from .commands import CommanderSettings

_log = structlog.get_logger("meshsa.command.config")

#: Policy-tuning bounds enforced as warnings now, hard rejections in a future release
#: (warn-not-reject so an out-of-range value can't fail-closed a node on restart).
#: Each entry is ``(field_name, human_requirement)``; the predicates live in
#: ``model_post_init``. ``port`` is NOT here — it is hard-validated (an unbindable port
#: can never have worked, so rejecting it is safe and beats an obscure bind crash).
_BOUNDS: tuple[tuple[str, str], ...] = (
    ("ack_timeout_s", "must be > 0"),
    ("max_attempts", "must be >= 1"),
    ("arm_report_max_age_s", "must be > 0"),
    ("target_system", "must be in 1..255"),
    ("target_component", "must be in 1..255"),
)


class CommanderConfig(BaseModel):
    """Validated commander config; ``to_settings()`` yields the policy dataclass."""

    model_config = ConfigDict(extra="ignore")

    host: str = "127.0.0.1"
    # Hard-validated (not warn-not-reject): an out-of-range port can never bind, so
    # reject it up front instead of warning then crashing obscurely in web.run_app.
    port: int = Field(default=8095, ge=1, le=65535)
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
        """Load + validate the commander JSON config from ``path``.

        Reads raw bytes so pydantic owns decoding: malformed UTF-8 or JSON surfaces as
        a ``ValidationError`` (not a stray ``UnicodeDecodeError``), keeping the caller's
        error handling to ``FileNotFoundError``/``OSError``/``ValidationError``.
        """
        return cls.model_validate_json(Path(path).read_bytes())

    @classmethod
    def from_env(
        cls, environ: Mapping[str, str] | None = None, prefix: str = "MESHSA_COMMANDER_"
    ) -> CommanderConfig:
        """Build config from environment variables; a ``<prefix>CONFIG_JSON``
        blob is merged first, then individual scalar overrides are applied."""
        import json
        import os

        env = dict(os.environ if environ is None else environ)
        data: dict[str, Any] = {}

        blob = env.get(f"{prefix}CONFIG_JSON")
        if blob:
            data.update(json.loads(blob))

        def _str(_name: str, value: str) -> str:
            return value

        def _set(_name: str, value: str) -> frozenset[str]:
            if value.startswith("[") and value.endswith("]"):
                try:
                    return frozenset(json.loads(value))
                except Exception:
                    pass
            return frozenset(x.strip() for x in value.split(",") if x.strip())

        scalar_map: dict[str, tuple[str, Callable[[str, str], Any]]] = {
            f"{prefix}HOST": ("host", _str),
            f"{prefix}PORT": ("port", parse_int),
            f"{prefix}MAVLINK_ENDPOINT": ("mavlink_endpoint", _str),
            f"{prefix}AUDIT_PATH": ("audit_path", _str),
            f"{prefix}TARGET_SYSTEM": ("target_system", parse_int),
            f"{prefix}TARGET_COMPONENT": ("target_component", parse_int),
            f"{prefix}ALLOWED": ("allowed", _set),
            f"{prefix}ALLOW_FORCE_DISARM": ("allow_force_disarm", _parse_bool),
            f"{prefix}ACK_TIMEOUT_S": ("ack_timeout_s", parse_float),
            f"{prefix}MAX_ATTEMPTS": ("max_attempts", parse_int),
            f"{prefix}ARM_REPORT_MAX_AGE_S": ("arm_report_max_age_s", parse_float),
        }

        for env_key, (field, caster) in scalar_map.items():
            if env_key in env:
                data[field] = caster(env_key, env[env_key])

        return cls.model_validate(data)
