"""Shared fixtures for the ``tools/agents_docs`` test files.

Synthetic cases build a throwaway git work tree under ``tmp_path`` rather than stubbing
``git ls-files``, so the enumeration path the linter depends on is the one under test.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tools.agents_docs import policy

REPO_ROOT = Path(__file__).resolve().parents[2]

#: A guide that satisfies every check, used as the baseline each failing case perturbs.
CLEAN_GUIDE = """\
# Example Agent Guide

## Traps

- The obvious command is the wrong one here.

## Rules

- Keep changes scoped — why: a wide diff hides the one line that mattered.
- Never commit secrets — why: a leaked key cannot be rotated quietly — control: literal_guard.
"""

#: A path-scoped rule that satisfies every check, including the two rule-only ones.
CLEAN_RULE = """\
---
paths:
  - "src/**/*.py"
---

# Example rule

## Rules

- Do a thing — why: a reason.
"""


def write(root: Path, rel: str, content: str) -> Path:
    """Write *content* to ``root/rel``, creating parents."""
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, capture_output=True, check=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """An initialised git work tree that ``git ls-files`` can enumerate."""
    git(tmp_path, "init", "-q")
    return tmp_path


@pytest.fixture
def one_guide_manifest(monkeypatch: pytest.MonkeyPatch) -> None:
    """Narrow GUIDE_MANIFEST to a single root guide for synthetic cases."""
    monkeypatch.setattr(policy, "GUIDE_MANIFEST", ("AGENTS.md",))
