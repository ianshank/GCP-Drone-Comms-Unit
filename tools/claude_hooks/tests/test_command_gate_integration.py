"""Integration: the REAL .claude/governance.yaml actually freezes the command path."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tools.claude_hooks.governance import load_governance, match_globs
from tools.claude_hooks.scope_freeze import NEXTSTEPS_QUOTE
from tools.claude_hooks.tests.helpers import SCOPE_FREEZE_SCRIPT, write_payload

REPO_ROOT = Path(__file__).resolve().parents[3]
REAL_CONFIG_PATH = REPO_ROOT / ".claude" / "governance.yaml"

#: The Initiative-C command-emission surfaces the freeze must cover.
EMISSION_PATHS = (
    "packages/meshsa/src/meshsa/command/service.py",
    "flightctl/run_commander.py",
)


def test_real_config_gate_is_closed() -> None:
    config = load_governance(REAL_CONFIG_PATH)
    assert config.c_gate_met is False, (
        "c_gate_met is human-set only; flipping it true is a maintainer decision "
        "recorded against docs/AUDIT_M2_AUTH.md"
    )


@pytest.mark.parametrize("rel_path", EMISSION_PATHS)
def test_real_config_covers_emission_path(rel_path: str) -> None:
    config = load_governance(REAL_CONFIG_PATH)
    assert match_globs(rel_path, config.command_emission_globs) is not None


@pytest.mark.parametrize("rel_path", EMISSION_PATHS)
def test_scope_freeze_denies_write_under_real_config(rel_path: str) -> None:
    config = load_governance(REAL_CONFIG_PATH)
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(REPO_ROOT)
    env.pop(config.override_env_var, None)  # a developer override must not leak in
    result = subprocess.run(
        [sys.executable, str(SCOPE_FREEZE_SCRIPT)],
        input=json.dumps(write_payload(str(REPO_ROOT / rel_path))),
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0
    output = json.loads(result.stdout)["hookSpecificOutput"]
    assert output["permissionDecision"] == "deny"
    assert NEXTSTEPS_QUOTE in output["permissionDecisionReason"]
