"""Task-checkbox reconciliation (ADVISORY): commit subjects vs OpenSpec bundles.

For every commit subject since :data:`BASELINE_SHA` that names a task id (``T-x.y`` or
a split half ``T-x.ya``), this checker verifies the corresponding checkbox in an
``openspec/changes/**/tasks.md`` bundle is ``[x]`` at HEAD. It exists because the
exact failure it detects has happened: Phase-2 work landed on main while the bundle
still showed the boxes unchecked, and the drift went unnoticed for weeks.

Advisory by design — checkbox mismatches print warnings and exit 0 (git history is
not always fixable: reverts, squash merges, and cross-bundle task-id collisions make
a hard gate brittle). A nonzero exit means the checker itself could not run. Wired
into ``scripts/validate-pre-pr.sh`` and the ``spec-driven-change`` reconciliation
playbook, not into required CI.

Usage::

    python tools/check_task_sync.py [--repo-root PATH] [--baseline SHA]
"""

from __future__ import annotations

import argparse
import logging
import re
import subprocess
import sys
from pathlib import Path
from typing import Final

_log = logging.getLogger("tools.check_task_sync")

#: First commit of the tech-debt foundation branch's history window. Commits at or
#: before this are grandfathered (their reconciliation happened in Phase A of the
#: code-hygiene foundation PR); move the baseline forward when a bundle archives.
BASELINE_SHA: Final[str] = "969af8e"

#: Task-id shapes: T-2.3, T-2.3a, T-10.2b. Only leading-subject mentions count —
#: a subject may name several ids separated by / or , (e.g. "T-2.7/T-2.9: ...").
_SUBJECT_IDS_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?P<ids>T-\d+\.\d+[a-z]?([/,]T-\d+\.\d+[a-z]?)*)[: ]"
)

#: Where bundles live, relative to the repo root (active and archived).
BUNDLE_GLOBS: Final[tuple[str, ...]] = (
    "openspec/changes/*/tasks.md",
    "openspec/changes/archive/*/tasks.md",
)


def _git_ok(repo_root: Path, *args: str) -> bool:
    """Whether ``git <args>`` succeeds in ``repo_root`` (no output captured)."""
    return (
        subprocess.run(  # noqa: S603 (fixed argv)
            ["git", *args],
            cwd=repo_root,
            capture_output=True,
            timeout=60,
            check=False,
        ).returncode
        == 0
    )


def is_git_repo(repo_root: Path) -> bool:
    """Whether ``repo_root`` is inside a git work tree at all.

    Kept distinct from :func:`baseline_reachable` so a genuinely broken invocation
    (run outside a checkout) still reports an operational error, rather than being
    silently absorbed by the missing-baseline path below.
    """
    return _git_ok(repo_root, "rev-parse", "--git-dir")


def baseline_reachable(repo_root: Path, baseline: str) -> bool:
    """Whether ``baseline`` resolves to a commit in this clone.

    It routinely will not: a squash merge replaces the branch's commits (so the
    recorded SHA vanishes from ``main``), and ``actions/checkout`` defaults to
    ``fetch-depth: 1``. Both are normal, neither is a checker failure — but
    ``git log <missing>..HEAD`` exits 128, and validate-pre-pr.sh counts any
    nonzero as a failed step, which would turn this advisory check into a hard
    red for every contributor after this branch merges.
    """
    return _git_ok(repo_root, "cat-file", "-e", f"{baseline}^{{commit}}")


def commit_subjects(repo_root: Path, baseline: str) -> list[str]:
    """Subjects of commits after ``baseline`` up to HEAD (empty list if none)."""
    result = subprocess.run(  # noqa: S603 (fixed argv)
        ["git", "log", "--format=%s", f"{baseline}..HEAD"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


def subject_task_ids(subject: str) -> list[str]:
    """Task ids named at the start of one commit subject (empty when none)."""
    match = _SUBJECT_IDS_RE.match(subject)
    if not match:
        return []
    return re.split(r"[/,]", match.group("ids"))


def bundle_checkbox_states(repo_root: Path) -> dict[str, dict[Path, bool]]:
    """``{task_id: {bundle_path: checked}}`` across every bundle tasks.md."""
    states: dict[str, dict[Path, bool]] = {}
    # `[X]` is valid GitHub-flavored Markdown for a checked box, and `*` is a valid
    # bullet — treating either as "no checkbox here" silently reported a landed task as
    # "not found in any bundle" rather than reconciling it.
    line_re = re.compile(r"^[-*] \[(?P<mark>[ xX])\] (?P<id>T-\d+\.\d+[a-z]?)\b")
    for pattern in BUNDLE_GLOBS:
        for tasks_md in repo_root.glob(pattern):
            for line in tasks_md.read_text(encoding="utf-8").splitlines():
                # Strip unconditionally: the regex is ^-anchored, so an INDENTED
                # sub-task ("  - [ ] T-1.2 ...") was silently invisible when the
                # strip was gated on the line already being unindented.
                match = line_re.match(line.strip())
                if not match:
                    continue
                checked = match.group("mark").lower() == "x"
                seen = states.setdefault(match.group("id"), {})
                if tasks_md in seen and seen[tasks_md] != checked:
                    # Same id listed twice in one file with different marks: last-write-
                    # wins would silently pick one. Record the ambiguity as unchecked so
                    # reconcile() surfaces it rather than reporting a confident answer.
                    seen[tasks_md] = False
                else:
                    seen.setdefault(tasks_md, checked)
    return states


def reconcile(repo_root: Path, baseline: str) -> tuple[list[str], int]:
    """(warnings, commits examined) for the ``baseline..HEAD`` window."""
    warnings: list[str] = []
    subjects = commit_subjects(repo_root, baseline)
    states = bundle_checkbox_states(repo_root)
    for subject in subjects:
        for task_id in subject_task_ids(subject):
            bundles = states.get(task_id)
            if bundles is None:
                warnings.append(
                    f"{task_id!r} (commit {subject!r}) not found in any bundle tasks.md"
                )
                continue
            if len(bundles) > 1:
                names = ", ".join(sorted(p.parent.name for p in bundles))
                warnings.append(f"{task_id!r} is defined in multiple bundles ({names}); skipping")
                continue
            ((bundle, checked),) = bundles.items()
            if not checked:
                warnings.append(
                    f"{task_id!r} has a landed commit ({subject!r}) but its checkbox in "
                    f"{bundle.parent.name}/tasks.md is still unchecked"
                )
    return warnings, len(subjects)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Warnings exit 0 (advisory); only operational errors exit 1."""
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(name)s: %(message)s")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--baseline", default=BASELINE_SHA)
    args = parser.parse_args(argv)
    repo_root = (args.repo_root or Path(__file__).resolve().parents[1]).resolve()
    _log.debug("reconciling task checkboxes under %s since %s", repo_root, args.baseline)
    try:
        if not is_git_repo(repo_root):
            _log.error("%s is not a git work tree", repo_root)
            print(f"task sync: cannot run: {repo_root} is not a git work tree", file=sys.stderr)
            return 1
        if not baseline_reachable(repo_root, args.baseline):
            _log.info(
                "baseline %s unreachable (squash merge or shallow checkout); skipping",
                args.baseline,
            )
            print(
                f"task sync: baseline {args.baseline} is not in this clone "
                f"(squash merge or shallow checkout); nothing to reconcile"
            )
            return 0
        warnings, examined = reconcile(repo_root, args.baseline)
    except (
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        OSError,
        UnicodeDecodeError,
    ) as exc:
        _log.error("cannot run: %s", exc)
        print(f"task sync: cannot run: {exc}", file=sys.stderr)
        return 1
    for warning in warnings:
        print(f"task sync: WARNING: {warning}")
    if warnings:
        _log.warning("task sync found %d warning(s) across %d commit(s)", len(warnings), examined)
    print(
        f"task sync: {examined} commit(s) examined since {args.baseline}, "
        f"{len(warnings)} warning(s) (advisory — exit 0)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
