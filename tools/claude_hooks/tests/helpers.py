"""Shared helpers for the governance hook tests: config builders and hook runners."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

#: Override env var used by all synthetic test configs (never the real one, so a
#: developer's environment cannot leak into a test run).
TEST_OVERRIDE_ENV_VAR = "TEST_GOVERNANCE_OVERRIDE"

#: Path of the scope_freeze hook script (run as a real subprocess, like the harness does).
SCOPE_FREEZE_SCRIPT = Path(__file__).resolve().parents[1] / "scope_freeze.py"


def governance_dict(**overrides: Any) -> dict[str, Any]:
    """A complete, valid governance mapping; keyword args override top-level keys."""
    data: dict[str, Any] = {
        "c_gate_met": False,
        "override_env_var": TEST_OVERRIDE_ENV_VAR,
        "command_emission_globs": [
            "packages/meshsa/src/meshsa/command/**",
            "flightctl/run_commander.py",
        ],
        "scope_widening_globs": ["packages/meshsa/src/meshsa/federation/**"],
        "bind_guard": {
            "required_symbol": "validate_bind",
            "canonical_module": "meshsa.netauth",
            "exceptions": [],
        },
    }
    data.update(overrides)
    return data


def write_governance(repo_root: Path, **overrides: Any) -> Path:
    """Write ``<repo_root>/.claude/governance.yaml`` from :func:`governance_dict`."""
    config_path = repo_root / ".claude" / "governance.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(yaml.safe_dump(governance_dict(**overrides)), encoding="utf-8")
    return config_path


def run_scope_freeze(
    repo_root: Path,
    payload: Any,
    *,
    extra_env: dict[str, str] | None = None,
    raw_stdin: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run scope_freeze.py as the harness would: JSON on stdin, env-configured root.

    ``raw_stdin`` (when given) is sent verbatim instead of serialising ``payload``,
    for malformed-input tests. The real override variable and the test one are
    scrubbed from the inherited environment unless supplied via ``extra_env``.
    """
    env = dict(os.environ)
    env.pop(TEST_OVERRIDE_ENV_VAR, None)
    env.pop("MESHSA_GOVERNANCE_OVERRIDE", None)
    env["CLAUDE_PROJECT_DIR"] = str(repo_root)
    env.update(extra_env or {})
    stdin_text = raw_stdin if raw_stdin is not None else json.dumps(payload)
    return subprocess.run(  # noqa: S603 (fixed argv, test-only)
        [sys.executable, str(SCOPE_FREEZE_SCRIPT)],
        input=stdin_text,
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        check=False,
    )


def write_payload(file_path: str, tool_name: str = "Write") -> dict[str, Any]:
    """A minimal PreToolUse payload for a file-writing tool call."""
    return {"tool_name": tool_name, "tool_input": {"file_path": file_path}}
