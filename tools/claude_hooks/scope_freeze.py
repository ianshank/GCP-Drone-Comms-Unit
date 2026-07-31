"""Claude Code PreToolUse hook enforcing the Initiative-C M2 scope freeze.

Reads the hook payload (JSON) from stdin, and when the targeted file matches a
frozen surface it emits a ``PreToolUse`` deny response on stdout:

* ``command_emission_globs`` while ``c_gate_met`` is false — the Initiative-C
  command send path is frozen per NEXTSTEPS.md ("do not ship a command surface
  before TLS + auth land");
* ``scope_widening_globs`` always — out-of-scope M3/M4 modules must not appear
  during M2.

Setting the configured override environment variable non-empty converts a
denial into an allow, logged to stderr. Malformed payloads, missing fields,
paths outside the repo, and an unreadable governance config all fail open
(allow) so a broken hook can never brick the session — the config itself lives
under ``.claude/`` and must remain editable to be fixed.

All policy (globs, override variable name) comes from ``.claude/governance.yaml``
via :mod:`tools.claude_hooks.governance`.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Final, TextIO

if __package__ in (None, ""):
    # Executed directly (`python tools/claude_hooks/scope_freeze.py` — the invocation
    # .claude/settings.json uses), so the repo root is not on sys.path as a package parent.
    # Add it and import the fully-qualified module below, rather than maintaining a second
    # import path to a differently-named top-level module (that duplication is what
    # previously made this file and tools/claude_hooks/governance.py resolve as two distinct
    # module identities under mypy — the same fix as bind_guard.py).
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.claude_hooks.governance import (
    GovernanceConfig,
    GovernanceConfigError,
    find_repo_root,
    load_governance,
    match_globs,
    to_repo_relative,
)

_log = logging.getLogger("claude_hooks.scope_freeze")

#: Hook event name echoed back in the deny response (Claude Code contract).
HOOK_EVENT_NAME: Final[str] = "PreToolUse"

#: Permission decision emitted for frozen paths (Claude Code contract).
DECISION_DENY: Final[str] = "deny"

#: Verbatim NEXTSTEPS.md sequencing rule quoted in command-path denials.
NEXTSTEPS_QUOTE: Final[str] = "do not ship a command surface before TLS + auth land"


def evaluate(config: GovernanceConfig, file_path: str, repo_root: Path) -> tuple[str, str] | None:
    """Return ``(category, reason)`` when ``file_path`` is frozen, else ``None``.

    Categories: ``"command_emission"`` (gate closed) or ``"scope_widening"``.
    """
    rel_path = to_repo_relative(file_path, repo_root)
    if rel_path is None:
        return None
    if not config.c_gate_met:
        pattern = match_globs(rel_path, config.command_emission_globs)
        if pattern is not None:
            reason = (
                f"Initiative-C command-emission freeze: {rel_path!r} matches {pattern!r} "
                f"and the M2 gate is not met (c_gate_met: false in .claude/governance.yaml). "
                f'NEXTSTEPS.md: "{NEXTSTEPS_QUOTE}". Clearing the gate is a maintainer '
                f"decision (see docs/AUDIT_M2_AUTH.md); to proceed anyway, set "
                f"{config.override_env_var} non-empty (the override is logged)."
            )
            return ("command_emission", reason)
    pattern = match_globs(rel_path, config.scope_widening_globs)
    if pattern is not None:
        reason = (
            f"M2 scope freeze: {rel_path!r} matches out-of-scope pattern {pattern!r} "
            f"(scope_widening_globs in .claude/governance.yaml). M3/M4 modules must not "
            f"appear during M2; extending the allowed scope is a maintainer decision. "
            f"To proceed anyway, set {config.override_env_var} non-empty (the override is logged)."
        )
        return ("scope_widening", reason)
    return None


def deny_response(reason: str) -> dict[str, Any]:
    """Build the Claude Code PreToolUse deny payload for ``reason``."""
    return {
        "hookSpecificOutput": {
            "hookEventName": HOOK_EVENT_NAME,
            "permissionDecision": DECISION_DENY,
            "permissionDecisionReason": reason,
        }
    }


def _read_payload(stream: TextIO) -> dict[str, Any] | None:
    """Parse the hook payload from ``stream``; ``None`` on anything malformed."""
    try:
        payload = json.load(stream)
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def main() -> int:
    """Hook entry point. Always exits 0; a deny is expressed via stdout JSON."""
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(name)s: %(message)s")
    payload = _read_payload(sys.stdin)
    if payload is None:
        _log.warning("malformed hook payload on stdin; allowing")
        return 0
    tool_name = payload.get("tool_name", "<unknown>")
    tool_input = payload.get("tool_input")
    file_path = tool_input.get("file_path") if isinstance(tool_input, dict) else None
    if not isinstance(file_path, str) or not file_path:
        return 0  # nothing to police (payload without a target path)
    try:
        repo_root = find_repo_root()
        config = load_governance()
    except GovernanceConfigError as exc:
        _log.warning("governance config unavailable; allowing: %s", exc)
        return 0
    verdict = evaluate(config, file_path, repo_root)
    if verdict is None:
        return 0
    category, reason = verdict
    if os.environ.get(config.override_env_var, ""):
        _log.warning(
            "override: env_var=%s tool=%s category=%s path=%s denied_reason=%r",
            config.override_env_var,
            tool_name,
            category,
            file_path,
            reason,
        )
        return 0
    _log.info("deny: tool=%s category=%s path=%s", tool_name, category, file_path)
    print(json.dumps(deny_response(reason)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
