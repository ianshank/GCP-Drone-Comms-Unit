"""check_tool_pins tests: pin extraction, rev extraction, mismatch detection."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from tools.check_tool_pins import (
    check,
    ci_workflow_pins,
    main,
    precommit_revs,
    pyproject_pins,
)

PYPROJECT_OK = 'dev = [\n    "ruff==0.16.3",\n    "mypy==2.3.0",\n]\n'
PRECOMMIT_OK = """\
repos:
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.30.1
    hooks: [{id: gitleaks}]
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.16.3
    hooks: [{id: ruff}]
  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v2.3.0
    hooks: [{id: mypy}]
"""
CI_OK = """\
jobs:
  governance:
    steps:
      - name: Secret scan (gitleaks)
        env:
          GITLEAKS_VERSION: 8.30.1
          GITLEAKS_SHA256: deadbeef
        run: echo "${GITLEAKS_VERSION}"
"""


def _write_repo(tmp_path: Path, pyproject: str, precommit: str, ci: str = CI_OK) -> Path:
    for rel in ("packages/meshsa", "packages/jetson_yolo_gcs"):
        (tmp_path / rel).mkdir(parents=True)
        (tmp_path / rel / "pyproject.toml").write_text(pyproject, encoding="utf-8")
    (tmp_path / ".pre-commit-config.yaml").write_text(precommit, encoding="utf-8")
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "ci.yml").write_text(ci, encoding="utf-8")
    return tmp_path


def test_pyproject_pins_extracts_exact_pins_only() -> None:
    text = '"ruff==0.16.3"\n"mypy>=1.10"\n"pytest==9.1.1"\n'
    assert pyproject_pins(text, "p.toml") == {"ruff": "0.16.3"}


def test_conflicting_pins_in_one_file_are_reported() -> None:
    text = '"ruff==0.16.3"\n"ruff==0.15.8"\n'
    assert pyproject_pins(text, "p.toml")["ruff"].startswith("CONFLICT(")


def test_precommit_revs_strips_leading_v() -> None:
    assert precommit_revs(PRECOMMIT_OK) == {"gitleaks": "8.30.1", "ruff": "0.16.3", "mypy": "2.3.0"}


def test_ci_workflow_pins_reads_the_env_value_quoted_or_not() -> None:
    assert ci_workflow_pins(CI_OK) == {"gitleaks": "8.30.1"}
    assert ci_workflow_pins('env:\n  GITLEAKS_VERSION: "v8.30.1"  # pinned\n') == {
        "gitleaks": "8.30.1"
    }
    assert ci_workflow_pins("steps: []\n") == {}


def test_ci_workflow_duplicate_versions_conflict() -> None:
    text = CI_OK + "          GITLEAKS_VERSION: 8.21.2\n"
    assert ci_workflow_pins(text)["gitleaks"].startswith("CONFLICT(")


def test_gitleaks_rev_disagreeing_with_ci_fails(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path, PYPROJECT_OK, PRECOMMIT_OK.replace("v8.30.1", "v8.21.2"))
    problems = check(repo)
    assert any("gitleaks pins disagree" in p for p in problems)
    assert not any("ruff" in p or "mypy" in p for p in problems)
    assert main(["--repo-root", str(repo)]) == 1


def test_gitleaks_is_not_expected_in_the_pyprojects(tmp_path: Path) -> None:
    # The pyprojects carry no gitleaks pin and must not be reported as missing one.
    repo = _write_repo(tmp_path, PYPROJECT_OK, PRECOMMIT_OK)
    assert check(repo) == []


def test_missing_ci_workflow_is_reported(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path, PYPROJECT_OK, PRECOMMIT_OK)
    (repo / ".github" / "workflows" / "ci.yml").unlink()
    problems = check(repo)
    assert any("missing .github/workflows/ci.yml" in p for p in problems)
    assert any("no exact gitleaks pin" in p and ".pre-commit" not in p for p in problems) is False


def test_in_sync_repo_is_clean(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path, PYPROJECT_OK, PRECOMMIT_OK)
    assert check(repo) == []
    assert main(["--repo-root", str(repo)]) == 0


def test_disagreeing_rev_fails(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path, PYPROJECT_OK, PRECOMMIT_OK.replace("v0.16.3", "v0.7.4"))
    problems = check(repo)
    assert any("ruff pins disagree" in p for p in problems)
    assert main(["--repo-root", str(repo)]) == 1


def test_missing_pin_fails(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path, '"mypy==2.3.0"\n', PRECOMMIT_OK)
    assert any("no exact ruff pin" in p for p in check(repo))


def test_missing_files_fail(tmp_path: Path) -> None:
    problems = check(tmp_path)
    assert any("missing pyproject" in p for p in problems)
    assert any("missing .pre-commit-config.yaml" in p for p in problems)
    assert any("missing .github/workflows/ci.yml" in p for p in problems)


@pytest.mark.parametrize("text", ["", "---\n", "# only a comment\n", "[]\n"])
def test_empty_precommit_config_is_a_clean_problem_not_a_crash(text: str, tmp_path: Path) -> None:
    # yaml.safe_load("") is None, not {} — calling .get on it raised an uncaught
    # AttributeError, so a truncated config produced a traceback instead of a verdict.
    repo = _write_repo(tmp_path, PYPROJECT_OK, text)
    problems = check(repo)
    assert any("no exact ruff pin" in p for p in problems)
    assert main(["--repo-root", str(repo)]) == 1


def test_repo_entry_without_a_rev_reports_a_missing_pin_and_names_the_file(
    tmp_path: Path,
) -> None:
    pc = "repos:\n  - repo: https://github.com/astral-sh/ruff-pre-commit\n    hooks: []\n"
    repo = _write_repo(tmp_path, PYPROJECT_OK, pc)
    problems = check(repo)
    assert any("no exact ruff pin" in p and ".pre-commit-config.yaml" in p for p in problems)


def test_duplicate_mirror_repos_conflict_like_duplicate_pyproject_pins() -> None:
    text = (
        PRECOMMIT_OK
        + """
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.7.4
    hooks: [{id: ruff}]
"""
    )
    assert precommit_revs(text)["ruff"].startswith("CONFLICT(")


def test_real_repo_is_in_sync() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    assert check(repo_root) == []


def test_disagreeing_rev_logs_a_warning(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    repo = _write_repo(tmp_path, PYPROJECT_OK, PRECOMMIT_OK.replace("v0.16.3", "v0.7.4"))
    with caplog.at_level(logging.WARNING, logger="tools.check_tool_pins"):
        assert main(["--repo-root", str(repo)]) == 1
    assert any("problem" in r.message for r in caplog.records)


def test_clean_repo_logs_no_warning(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    repo = _write_repo(tmp_path, PYPROJECT_OK, PRECOMMIT_OK)
    with caplog.at_level(logging.WARNING, logger="tools.check_tool_pins"):
        assert main(["--repo-root", str(repo)]) == 0
    assert caplog.records == []
