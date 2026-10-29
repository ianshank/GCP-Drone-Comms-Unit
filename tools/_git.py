"""The one ``subprocess.run(["git", …])`` wrapper the checkers share (plan P2-6).

``check_task_sync`` and ``agents_docs`` each ran git with the same fixed-argv boilerplate
(capture, timeout, the ``# noqa: S603`` justification) five times between them. Two
shapes cover every call: a yes/no probe (:func:`git_ok`) and a line-list query
(:func:`git_lines`). The subcommand and its flags are always literals; the one
caller-supplied value anywhere (``check_task_sync``'s ``--baseline`` revision) is passed
after ``--end-of-options`` so it can never be parsed as a flag. That, plus list argv (no
shell), is what the single ``S603`` waiver below asserts.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Final

#: Upper bound on one git invocation; generous because CI runners can be slow to page a
#: cold checkout in, and a hang here would otherwise stall the whole governance job.
GIT_TIMEOUT_S: Final = 60


def git_ok(root: Path, *args: str, timeout: float = GIT_TIMEOUT_S) -> bool:
    """Whether ``git <args>`` exits 0 in ``root`` (output discarded, never raises)."""
    return _run(root, args, timeout=timeout, check=False).returncode == 0


def git_lines(root: Path, *args: str, timeout: float = GIT_TIMEOUT_S) -> list[str]:
    """Stdout of ``git <args>`` in ``root`` as lines; raises ``CalledProcessError`` on failure."""
    return _run(root, args, timeout=timeout, check=True).stdout.splitlines()


def _run(
    root: Path, args: tuple[str, ...], *, timeout: float, check: bool
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 (list argv, literal subcommand; see module docstring)
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=check,
    )
