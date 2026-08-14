"""check_task_sync tests: subject parsing, checkbox states, advisory reconciliation."""

from __future__ import annotations

import subprocess
from pathlib import Path

from tools.check_task_sync import (
    bundle_checkbox_states,
    main,
    reconcile,
    subject_task_ids,
)


def test_subject_task_ids_parses_leading_ids_only() -> None:
    assert subject_task_ids("T-2.3a: safe deletions") == ["T-2.3a"]
    assert subject_task_ids("T-2.7/T-2.9: CI determinism") == ["T-2.7", "T-2.9"]
    assert subject_task_ids("Phase A: reconcile tasks.md (T-2.1)") == []
    assert subject_task_ids("fix: unrelated") == []


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        env={
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
            "PATH": "/usr/bin:/bin:/usr/local/bin",
            "HOME": str(repo),
        },
    )


def _repo_with_bundle(tmp_path: Path, tasks_md: str) -> tuple[Path, str]:
    """A throwaway git repo with one bundle; returns (repo, baseline sha)."""
    _git(tmp_path, "init", "-q")
    bundle = tmp_path / "openspec/changes/demo"
    bundle.mkdir(parents=True)
    (bundle / "tasks.md").write_text(tasks_md, encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "baseline")
    out = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True, check=True
    )
    return tmp_path, out.stdout.strip()


def test_bundle_checkbox_states_reads_both_marks(tmp_path: Path) -> None:
    repo, _ = _repo_with_bundle(tmp_path, "- [x] T-1.1 done\n- [ ] T-1.2 open\n")
    states = bundle_checkbox_states(repo)
    assert list(states["T-1.1"].values()) == [True]
    assert list(states["T-1.2"].values()) == [False]


def test_landed_but_unchecked_task_warns(tmp_path: Path) -> None:
    repo, baseline = _repo_with_bundle(tmp_path, "- [ ] T-1.2 open\n")
    (repo / "f.txt").write_text("x", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "T-1.2: land the thing")
    warnings, examined = reconcile(repo, baseline)
    assert examined == 1
    assert any("still unchecked" in w for w in warnings)
    # Advisory: warnings never fail the run.
    assert main(["--repo-root", str(repo), "--baseline", baseline]) == 0


def test_checked_task_is_clean(tmp_path: Path) -> None:
    repo, baseline = _repo_with_bundle(tmp_path, "- [x] T-1.2 done\n")
    (repo / "f.txt").write_text("x", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "T-1.2: land the thing")
    warnings, _ = reconcile(repo, baseline)
    assert warnings == []


def test_unknown_and_ambiguous_ids_warn_and_skip(tmp_path: Path) -> None:
    repo, baseline = _repo_with_bundle(tmp_path, "- [ ] T-1.2 open\n")
    second = repo / "openspec/changes/other"
    second.mkdir(parents=True)
    (second / "tasks.md").write_text("- [x] T-1.2 same id, other bundle\n", encoding="utf-8")
    (repo / "f.txt").write_text("x", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "T-1.2: ambiguous")
    (repo / "g.txt").write_text("x", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "T-9.9: no such task")
    warnings, examined = reconcile(repo, baseline)
    assert examined == 2
    assert any("multiple bundles" in w for w in warnings)
    assert any("not found in any bundle" in w for w in warnings)


def test_operational_error_exits_nonzero(tmp_path: Path) -> None:
    # Not a git repo: the checker cannot run, which is the one nonzero case.
    assert main(["--repo-root", str(tmp_path)]) == 1
