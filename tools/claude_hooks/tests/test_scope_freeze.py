"""scope_freeze hook tests, driven end-to-end as a subprocess (stdin JSON in, JSON out)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tools.claude_hooks.scope_freeze import DECISION_DENY, HOOK_EVENT_NAME, NEXTSTEPS_QUOTE
from tools.claude_hooks.tests.helpers import (
    TEST_OVERRIDE_ENV_VAR,
    run_scope_freeze,
    write_governance,
    write_payload,
)

COMMAND_REL_PATH = "packages/meshsa/src/meshsa/command/service.py"
FEDERATION_REL_PATH = "packages/meshsa/src/meshsa/federation/gossip.py"


def _deny_reason(stdout: str) -> str:
    """Parse the hook's stdout and return the deny reason (asserting the contract)."""
    response: dict[str, Any] = json.loads(stdout)
    output = response["hookSpecificOutput"]
    assert output["hookEventName"] == HOOK_EVENT_NAME
    assert output["permissionDecision"] == DECISION_DENY
    reason = output["permissionDecisionReason"]
    assert isinstance(reason, str) and reason
    return reason


def test_denies_command_glob_while_gate_false(tmp_path: Path) -> None:
    write_governance(tmp_path)
    result = run_scope_freeze(tmp_path, write_payload(str(tmp_path / COMMAND_REL_PATH)))
    assert result.returncode == 0
    reason = _deny_reason(result.stdout)
    assert NEXTSTEPS_QUOTE in reason
    assert "c_gate_met" in reason


def test_denies_repo_relative_command_path(tmp_path: Path) -> None:
    write_governance(tmp_path)
    result = run_scope_freeze(tmp_path, write_payload(COMMAND_REL_PATH, tool_name="Edit"))
    assert result.returncode == 0
    assert NEXTSTEPS_QUOTE in _deny_reason(result.stdout)


def test_allows_command_glob_when_gate_met(tmp_path: Path) -> None:
    write_governance(tmp_path, c_gate_met=True)
    result = run_scope_freeze(tmp_path, write_payload(str(tmp_path / COMMAND_REL_PATH)))
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_denies_scope_widening_even_when_gate_met(tmp_path: Path) -> None:
    write_governance(tmp_path, c_gate_met=True)
    result = run_scope_freeze(tmp_path, write_payload(str(tmp_path / FEDERATION_REL_PATH)))
    assert result.returncode == 0
    reason = _deny_reason(result.stdout)
    assert "scope_widening_globs" in reason


def test_allows_unrelated_path(tmp_path: Path) -> None:
    write_governance(tmp_path)
    result = run_scope_freeze(
        tmp_path, write_payload(str(tmp_path / "packages/meshsa/src/meshsa/router.py"))
    )
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_allows_absolute_path_outside_repo(tmp_path: Path) -> None:
    write_governance(tmp_path)
    outside = tmp_path.parent / "other-repo" / COMMAND_REL_PATH
    result = run_scope_freeze(tmp_path, write_payload(str(outside)))
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_override_env_allows_and_logs(tmp_path: Path) -> None:
    write_governance(tmp_path)
    target = str(tmp_path / COMMAND_REL_PATH)
    result = run_scope_freeze(
        tmp_path, write_payload(target), extra_env={TEST_OVERRIDE_ENV_VAR: "1"}
    )
    assert result.returncode == 0
    assert result.stdout.strip() == ""  # no deny emitted
    assert "override" in result.stderr
    assert TEST_OVERRIDE_ENV_VAR in result.stderr
    assert target in result.stderr


def test_override_env_empty_string_still_denies(tmp_path: Path) -> None:
    write_governance(tmp_path)
    result = run_scope_freeze(
        tmp_path,
        write_payload(str(tmp_path / COMMAND_REL_PATH)),
        extra_env={TEST_OVERRIDE_ENV_VAR: ""},
    )
    assert result.returncode == 0
    assert NEXTSTEPS_QUOTE in _deny_reason(result.stdout)


def test_malformed_stdin_allows(tmp_path: Path) -> None:
    write_governance(tmp_path)
    result = run_scope_freeze(tmp_path, None, raw_stdin="this is {not json")
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_missing_file_path_field_allows(tmp_path: Path) -> None:
    write_governance(tmp_path)
    result = run_scope_freeze(tmp_path, {"tool_name": "Write", "tool_input": {}})
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_missing_tool_input_allows(tmp_path: Path) -> None:
    write_governance(tmp_path)
    result = run_scope_freeze(tmp_path, {"tool_name": "Write"})
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_missing_governance_config_fails_open(tmp_path: Path) -> None:
    # No .claude/governance.yaml in the project dir: the hook must allow (and say why
    # on stderr) rather than lock every Write/Edit behind a broken config.
    result = run_scope_freeze(tmp_path, write_payload(str(tmp_path / COMMAND_REL_PATH)))
    assert result.returncode == 0
    assert result.stdout.strip() == ""
    assert "governance config unavailable" in result.stderr
