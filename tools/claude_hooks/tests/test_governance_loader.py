"""Loader tests: schema acceptance/rejection, default path resolution, glob helpers."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tools.claude_hooks.governance import (
    GovernanceConfigError,
    default_governance_path,
    find_repo_root,
    load_governance,
    match_globs,
    to_repo_relative,
)
from tools.claude_hooks.tests.helpers import governance_dict, write_governance


class TestLoadGovernance:
    def test_valid_config_loads(self, tmp_path: Path) -> None:
        config_path = write_governance(tmp_path)
        config = load_governance(config_path)
        assert config.c_gate_met is False
        assert config.override_env_var == "TEST_GOVERNANCE_OVERRIDE"
        assert "flightctl/run_commander.py" in config.command_emission_globs
        assert config.bind_guard.required_symbol == "validate_bind"
        assert config.bind_guard.canonical_module == "meshsa.netauth"
        assert config.bind_guard.exceptions == []

    def test_exceptions_entries_load(self, tmp_path: Path) -> None:
        bind_guard = governance_dict()["bind_guard"]
        bind_guard["exceptions"] = [{"path": "a/b.py", "rationale": "multicast"}]
        config_path = write_governance(tmp_path, bind_guard=bind_guard)
        config = load_governance(config_path)
        assert config.bind_guard.exceptions[0].path == "a/b.py"
        assert config.bind_guard.exceptions[0].rationale == "multicast"

    def test_unknown_top_level_key_rejected(self, tmp_path: Path) -> None:
        config_path = write_governance(tmp_path, surprise_key=True)
        with pytest.raises(GovernanceConfigError, match="surprise_key"):
            load_governance(config_path)

    def test_unknown_nested_key_rejected(self, tmp_path: Path) -> None:
        bind_guard = governance_dict()["bind_guard"]
        bind_guard["escape_hatch"] = "no"
        config_path = write_governance(tmp_path, bind_guard=bind_guard)
        with pytest.raises(GovernanceConfigError, match="escape_hatch"):
            load_governance(config_path)

    def test_missing_required_key_rejected(self, tmp_path: Path) -> None:
        data = governance_dict()
        del data["c_gate_met"]
        config_path = tmp_path / "governance.yaml"
        config_path.write_text(yaml.safe_dump(data), encoding="utf-8")
        with pytest.raises(GovernanceConfigError, match="c_gate_met"):
            load_governance(config_path)

    def test_bad_value_rejected(self, tmp_path: Path) -> None:
        config_path = write_governance(tmp_path, c_gate_met="definitely")
        with pytest.raises(GovernanceConfigError, match="c_gate_met"):
            load_governance(config_path)

    def test_missing_file_raises_clean_error(self, tmp_path: Path) -> None:
        missing = tmp_path / "nope" / "governance.yaml"
        with pytest.raises(GovernanceConfigError, match="not found"):
            load_governance(missing)

    def test_invalid_yaml_raises(self, tmp_path: Path) -> None:
        config_path = tmp_path / "governance.yaml"
        config_path.write_text("c_gate_met: [unterminated", encoding="utf-8")
        with pytest.raises(GovernanceConfigError, match="not valid YAML"):
            load_governance(config_path)

    def test_non_mapping_document_raises(self, tmp_path: Path) -> None:
        config_path = tmp_path / "governance.yaml"
        config_path.write_text("- just\n- a list\n", encoding="utf-8")
        with pytest.raises(GovernanceConfigError, match="mapping"):
            load_governance(config_path)


class TestDefaultPath:
    def test_env_var_wins(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        assert find_repo_root() == tmp_path.resolve()
        assert default_governance_path() == tmp_path.resolve() / ".claude" / "governance.yaml"

    def test_walk_up_finds_dot_claude(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Without the env var, the walk-up from the module location must land on
        # this repository's root (which contains .claude/).
        monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
        root = find_repo_root()
        assert (root / ".claude").is_dir()
        assert (root / "tools" / "claude_hooks" / "governance.py").is_file()


class TestPathAndGlobHelpers:
    def test_relative_path_normalised(self, tmp_path: Path) -> None:
        assert to_repo_relative("./flightctl/run_commander.py", tmp_path) == (
            "flightctl/run_commander.py"
        )

    def test_absolute_path_inside_repo(self, tmp_path: Path) -> None:
        target = tmp_path / "flightctl" / "run_commander.py"
        assert to_repo_relative(str(target), tmp_path) == "flightctl/run_commander.py"

    def test_absolute_path_outside_repo_is_none(self, tmp_path: Path) -> None:
        outside = tmp_path.parent / "elsewhere" / "x.py"
        assert to_repo_relative(str(outside), tmp_path / "repo") is None

    def test_match_globs_recursive_pattern(self) -> None:
        globs = ["packages/meshsa/src/meshsa/command/**"]
        assert match_globs("packages/meshsa/src/meshsa/command/service.py", globs)
        assert match_globs("packages/meshsa/src/meshsa/command/sub/deep.py", globs)
        assert match_globs("packages/meshsa/src/meshsa/command", globs)
        assert match_globs("packages/meshsa/src/meshsa/router.py", globs) is None

    def test_match_globs_exact_file(self) -> None:
        globs = ["flightctl/run_commander.py"]
        assert match_globs("flightctl/run_commander.py", globs)
        assert match_globs("flightctl/run_gateway.py", globs) is None
