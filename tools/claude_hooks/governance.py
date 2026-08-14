"""Governance configuration for the Claude Code hook tooling.

Loads and validates ``.claude/governance.yaml`` — the single source of policy for
the M2 scope freeze (:mod:`tools.claude_hooks.scope_freeze`) and the bind-guard
linter (:mod:`tools.claude_hooks.bind_guard`). No policy values (glob lists,
override variable name, canonical auth module) live in code; they all come from
this config file.

The default config location is derived from the repository root, which is
resolved from the ``CLAUDE_PROJECT_DIR`` environment variable when set (the
Claude Code harness exports it for hooks), falling back to walking up from this
file until a directory containing ``.claude/`` is found. No absolute paths are
hardcoded.
"""

from __future__ import annotations

import fnmatch
import logging
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Final

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

_log = logging.getLogger(__name__)

#: Environment variable the Claude Code harness sets to the repository root.
PROJECT_DIR_ENV: Final[str] = "CLAUDE_PROJECT_DIR"

#: Directory (relative to the repo root) that marks the root and holds the config.
CLAUDE_DIR_NAME: Final[str] = ".claude"

#: Governance config filename inside :data:`CLAUDE_DIR_NAME`.
GOVERNANCE_FILENAME: Final[str] = "governance.yaml"


class GovernanceConfigError(RuntimeError):
    """Raised when the governance config is missing, unparsable, or invalid."""


class BindGuardExceptionEntry(BaseModel):
    """A declared bind-guard exception: one repo-relative path plus its rationale."""

    model_config = ConfigDict(extra="forbid")

    path: str
    rationale: str


class BindGuardConfig(BaseModel):
    """Policy for the bind-guard linter (single audited bind primitive)."""

    model_config = ConfigDict(extra="forbid")

    required_symbol: str
    canonical_module: str
    exceptions: list[BindGuardExceptionEntry]


class LiteralGuardExceptionEntry(BaseModel):
    """A declared literal-guard exception: repo-relative path, rule, and rationale.

    ``rule`` names one of the checker's rule identifiers (``ports``, ``hosts``,
    ``magics``, ``endpoints``) or ``*`` for all rules — a scoped waiver, so a file
    excepted for one literal class stays scanned for the others.
    """

    model_config = ConfigDict(extra="forbid")

    path: str
    rule: str
    rationale: str


class LiteralGuardConfig(BaseModel):
    """Policy for the literal-guard linter (service literals live in one module)."""

    model_config = ConfigDict(extra="forbid")

    defaults_module: str
    exceptions: list[LiteralGuardExceptionEntry]


class GovernanceConfig(BaseModel):
    """Validated shape of ``.claude/governance.yaml`` (no extra keys allowed).

    ``literal_guard`` is optional (default ``None``) deliberately: the scope-freeze
    hook fails open on a config it cannot validate, so a required new section would
    open a mid-edit window — whichever of loader/yaml changed first would invalidate
    the other. Optional-with-default keeps every loader/yaml combination valid during
    rollout; :mod:`tools.claude_hooks.literal_guard` errors cleanly when the section
    is absent.
    """

    model_config = ConfigDict(extra="forbid")

    c_gate_met: bool
    override_env_var: str
    command_emission_globs: list[str]
    scope_widening_globs: list[str]
    bind_guard: BindGuardConfig
    literal_guard: LiteralGuardConfig | None = None


def find_repo_root() -> Path:
    """Resolve the repository root without hardcoding any absolute path.

    Prefers :data:`PROJECT_DIR_ENV` (set by the Claude Code harness); otherwise
    walks up from this file's location looking for a ``.claude/`` directory.
    """
    env_root = os.environ.get(PROJECT_DIR_ENV)
    if env_root:
        return Path(env_root).resolve()
    here = Path(__file__).resolve()
    for candidate in here.parents:
        if (candidate / CLAUDE_DIR_NAME).is_dir():
            return candidate
    raise GovernanceConfigError(
        f"cannot locate repository root: {PROJECT_DIR_ENV} is unset and no "
        f"{CLAUDE_DIR_NAME}/ directory was found above {here}"
    )


def default_governance_path() -> Path:
    """Default config path: ``<repo root>/.claude/governance.yaml`` (see module doc)."""
    return find_repo_root() / CLAUDE_DIR_NAME / GOVERNANCE_FILENAME


def load_governance(path: Path | None = None) -> GovernanceConfig:
    """Load and validate the governance config.

    Args:
        path: Config file to load; defaults to :func:`default_governance_path`.

    Raises:
        GovernanceConfigError: with a clean, operator-facing message when the
            file is missing, is not valid YAML, or fails schema validation
            (including unknown keys).
    """
    resolved = path if path is not None else default_governance_path()
    if not resolved.is_file():
        raise GovernanceConfigError(f"governance config not found: {resolved}")
    try:
        raw = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise GovernanceConfigError(
            f"governance config is not valid YAML: {resolved}: {exc}"
        ) from exc
    if not isinstance(raw, dict):
        raise GovernanceConfigError(
            f"governance config must be a YAML mapping, got {type(raw).__name__}: {resolved}"
        )
    try:
        return GovernanceConfig.model_validate(raw)
    except ValidationError as exc:
        raise GovernanceConfigError(f"invalid governance config {resolved}: {exc}") from exc


def to_repo_relative(path: str, repo_root: Path) -> str | None:
    """Normalise ``path`` to a posix-style repo-relative string.

    Accepts absolute or repo-relative input (the hook payload may carry either)
    and Windows-style separators. Returns ``None`` for absolute paths that fall
    outside ``repo_root`` — such paths can never match repo-relative globs.
    """
    normalized = path.replace("\\", "/")
    root = repo_root.resolve()
    candidate = Path(normalized)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        return candidate.resolve().relative_to(root).as_posix()
    except ValueError:
        return None


def match_globs(rel_path: str, patterns: Iterable[str]) -> str | None:
    """Return the first glob in ``patterns`` matching ``rel_path``, else ``None``.

    ``rel_path`` must be posix-style and repo-relative (see
    :func:`to_repo_relative`). Matching is case-sensitive on the full relative
    path; a trailing ``/**`` also matches the directory itself.
    """
    for pattern in patterns:
        if fnmatch.fnmatchcase(rel_path, pattern):
            return pattern
        if pattern.endswith("/**") and fnmatch.fnmatchcase(rel_path, pattern[: -len("/**")]):
            return pattern
    return None
