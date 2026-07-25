"""Tests for tools/validate_workforce.py against synthetic and real rosters."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

TOOLS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = TOOLS_DIR.parent
sys.path.insert(0, str(TOOLS_DIR))

import validate_workforce as vw  # noqa: E402

VALID_TEMPLATE = """\
---
name: {name}
description: "Does one M2 thing."
tools: Read, Grep
---

Terse body.

Relationship: {relationship}
"""


def write_agent(
    roster: Path,
    filename: str,
    *,
    name: str | None = None,
    relationship: str = "none — new mandate.",
    content: str | None = None,
) -> Path:
    roster.mkdir(parents=True, exist_ok=True)
    path = roster / filename
    if content is None:
        content = VALID_TEMPLATE.format(name=name or path.stem, relationship=relationship)
    path.write_text(content, encoding="utf-8")
    return path


@pytest.fixture
def roster(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Synthetic roster dir with tmp_path acting as the repo root."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    return tmp_path / ".claude" / "agents"


def test_valid_roster_passes(roster: Path, tmp_path: Path) -> None:
    write_agent(roster, "alpha.md")
    write_agent(roster, "beta.md")
    assert vw.validate_roster(roster, tmp_path) == []
    assert vw.main(["--roster-dir", str(roster)]) == 0


def test_missing_frontmatter_key_fails(roster: Path, tmp_path: Path) -> None:
    content = "---\nname: alpha\ndescription: x\n---\n\nRelationship: none — new mandate.\n"
    write_agent(roster, "alpha.md", content=content)
    findings = vw.validate_roster(roster, tmp_path)
    assert any("missing required key(s): tools" in finding for finding in findings)


def test_name_filename_mismatch_fails(roster: Path, tmp_path: Path) -> None:
    write_agent(roster, "alpha.md", name="omega")
    findings = vw.validate_roster(roster, tmp_path)
    assert any("'omega' != filename stem 'alpha'" in finding for finding in findings)


def test_over_length_file_fails(roster: Path, tmp_path: Path) -> None:
    padding = "filler line\n" * (vw.MAX_LINES + 1)
    content = VALID_TEMPLATE.format(name="alpha", relationship="none — new mandate.") + padding
    write_agent(roster, "alpha.md", content=content)
    findings = vw.validate_roster(roster, tmp_path)
    assert any(f"exceeds the {vw.MAX_LINES}-line limit" in finding for finding in findings)


def test_missing_relationship_line_fails(roster: Path, tmp_path: Path) -> None:
    content = "---\nname: alpha\ndescription: x\ntools: Read\n---\n\nBody only.\n"
    write_agent(roster, "alpha.md", content=content)
    findings = vw.validate_roster(roster, tmp_path)
    assert any("no line starting with 'Relationship:'" in finding for finding in findings)


def test_relationship_path_must_exist(roster: Path, tmp_path: Path) -> None:
    write_agent(roster, "alpha.md", relationship="tools/does-not-exist.py (missing).")
    findings = vw.validate_roster(roster, tmp_path)
    assert any("does not exist in repo: tools/does-not-exist.py" in finding for finding in findings)


def test_relationship_existing_path_passes(roster: Path, tmp_path: Path) -> None:
    (tmp_path / ".agents" / "skills" / "demo").mkdir(parents=True)
    write_agent(roster, "alpha.md", relationship=".agents/skills/demo (sibling playbook).")
    assert vw.validate_roster(roster, tmp_path) == []


def test_duplicate_names_fail(roster: Path, tmp_path: Path) -> None:
    write_agent(roster, "alpha.md", name="alpha")
    write_agent(roster, "beta.md", name="alpha")
    findings = vw.validate_roster(roster, tmp_path)
    assert any("duplicate agent name 'alpha'" in finding for finding in findings)


def test_empty_roster_dir_fails(roster: Path, tmp_path: Path) -> None:
    roster.mkdir(parents=True)
    findings = vw.validate_roster(roster, tmp_path)
    assert findings == [f"{roster}: contains no .md roster files"]
    assert vw.main(["--roster-dir", str(roster)]) == 1


def test_missing_roster_dir_fails(roster: Path, tmp_path: Path) -> None:
    findings = vw.validate_roster(roster, tmp_path)
    assert findings == [f"{roster}: roster directory does not exist"]


def test_real_roster_passes_via_cli() -> None:
    """Integration: the committed .claude/agents roster must be clean."""
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(REPO_ROOT)}
    result = subprocess.run(
        [sys.executable, str(TOOLS_DIR / "validate_workforce.py")],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.startswith("OK: 7 roster file(s)")
