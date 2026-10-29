"""Tests for ``tools/_git.py``, the git wrapper the checkers share (plan P2-6)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tools._git import GIT_TIMEOUT_S, git_lines, git_ok
from tools.tests.conftest import git, write


def test_git_ok_reports_success_and_failure_without_raising(
    repo: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    assert git_ok(repo, "rev-parse", "--git-dir") is True
    outside = tmp_path_factory.mktemp("not-a-repo")  # a sibling of the repo, not inside it
    assert git_ok(outside, "rev-parse", "--git-dir") is False


def test_git_lines_returns_stdout_split_into_lines(repo: Path) -> None:
    write(repo, "a.txt", "x")
    write(repo, "b/c.txt", "y")
    git(repo, "add", ".")
    assert git_lines(repo, "ls-files") == ["a.txt", "b/c.txt"]


def test_git_lines_raises_on_a_failing_command(repo: Path) -> None:
    with pytest.raises(subprocess.CalledProcessError):
        git_lines(repo, "cat-file", "-e", "deadbeef^{commit}")


def test_timeout_is_passed_through(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen: dict[str, object] = {}

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        seen["argv"] = argv
        seen.update(kwargs)
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert git_ok(tmp_path, "status", timeout=5) is True
    assert seen["argv"] == ["git", "status"]
    assert seen["timeout"] == 5
    assert seen["cwd"] == tmp_path
    git_lines(tmp_path, "status")
    assert seen["timeout"] == GIT_TIMEOUT_S
