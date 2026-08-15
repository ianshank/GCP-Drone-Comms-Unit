"""Tests for tools/validate_skills.py against synthetic and real skill playbooks."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

import tools.validate_skills as vs
from tools.validate_skills import (
    cited_path_findings,
    main,
    validate_skills,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

VALID_TEMPLATE = """\
---
name: {name}
description: "Use when: doing one specific thing."
argument-hint: "The thing and its scope"
---

# {name}

## When to Use

- One clear trigger.

## Procedure

1. Do the thing.
"""


def write_skill(
    skills_dir: Path,
    dirname: str,
    *,
    name: str | None = None,
    content: str | None = None,
) -> Path:
    skill_dir = skills_dir / dirname
    skill_dir.mkdir(parents=True, exist_ok=True)
    path = skill_dir / "SKILL.md"
    if content is None:
        content = VALID_TEMPLATE.format(name=name or dirname)
    path.write_text(content, encoding="utf-8")
    return path


@pytest.fixture
def skills_dir(tmp_path: Path) -> Path:
    """Synthetic skills dir with tmp_path acting as the repo root."""
    return tmp_path / ".agents" / "skills"


def test_valid_skills_dir_passes(skills_dir: Path, tmp_path: Path) -> None:
    write_skill(skills_dir, "alpha")
    write_skill(skills_dir, "beta")
    assert validate_skills(skills_dir, tmp_path) == []
    assert main(["--skills-dir", str(skills_dir)]) == 0


def test_missing_frontmatter_key_fails(skills_dir: Path, tmp_path: Path) -> None:
    content = '---\nname: alpha\ndescription: "Use when: x"\n---\n\n## Procedure\n\nDo it.\n'
    write_skill(skills_dir, "alpha", content=content)
    findings = validate_skills(skills_dir, tmp_path)
    assert any("missing required key(s): argument-hint" in f for f in findings)


def test_name_directory_mismatch_fails(skills_dir: Path, tmp_path: Path) -> None:
    write_skill(skills_dir, "alpha", name="omega")
    findings = validate_skills(skills_dir, tmp_path)
    assert any("'omega' != skill directory 'alpha'" in f for f in findings)


def test_description_missing_use_when_prefix_fails(skills_dir: Path, tmp_path: Path) -> None:
    content = (
        "---\n"
        "name: alpha\n"
        'description: "Something that does not follow the trigger convention."\n'
        'argument-hint: "x"\n'
        "---\n\n## Procedure\n\nDo it.\n"
    )
    write_skill(skills_dir, "alpha", content=content)
    findings = validate_skills(skills_dir, tmp_path)
    assert any("does not start with 'Use when:'" in f for f in findings)


def test_body_with_no_heading_fails(skills_dir: Path, tmp_path: Path) -> None:
    content = (
        "---\n"
        "name: alpha\n"
        'description: "Use when: x"\n'
        'argument-hint: "x"\n'
        "---\n\nJust prose, no section headings.\n"
    )
    write_skill(skills_dir, "alpha", content=content)
    findings = validate_skills(skills_dir, tmp_path)
    assert any("fewer than 1 '## ' section heading" in f for f in findings)


def test_duplicate_skill_names_fail(skills_dir: Path, tmp_path: Path) -> None:
    write_skill(skills_dir, "alpha", name="alpha")
    write_skill(skills_dir, "beta", name="alpha")
    findings = validate_skills(skills_dir, tmp_path)
    assert any("duplicate skill name 'alpha'" in f for f in findings)


def test_empty_skills_dir_fails(skills_dir: Path, tmp_path: Path) -> None:
    skills_dir.mkdir(parents=True)
    findings = validate_skills(skills_dir, tmp_path)
    assert findings == [f"{skills_dir}: contains no */SKILL.md files"]
    assert main(["--skills-dir", str(skills_dir)]) == 1


def test_missing_skills_dir_fails(skills_dir: Path, tmp_path: Path) -> None:
    findings = validate_skills(skills_dir, tmp_path)
    assert findings == [f"{skills_dir}: skills directory does not exist"]


# ---- cited_path_findings ----------------------------------------------------
def test_cited_missing_root_path_is_flagged(tmp_path: Path) -> None:
    body = ["See `packages/meshsa/src/meshsa/does_not_exist.py` for details."]
    assert cited_path_findings(body, tmp_path) == ["packages/meshsa/src/meshsa/does_not_exist.py"]


def test_cited_existing_root_path_passes(tmp_path: Path) -> None:
    target = tmp_path / "docs" / "real.md"
    target.parent.mkdir(parents=True)
    target.write_text("x", encoding="utf-8")
    body = ["See `docs/real.md` for details."]
    assert cited_path_findings(body, tmp_path) == []


def test_bare_root_file_is_checked(tmp_path: Path) -> None:
    body = ["Read `AGENTS.md` first."]
    assert cited_path_findings(body, tmp_path) == ["AGENTS.md"]
    (tmp_path / "AGENTS.md").write_text("x", encoding="utf-8")
    assert cited_path_findings(body, tmp_path) == []


def test_package_relative_shorthand_is_not_flagged(tmp_path: Path) -> None:
    # `mavlink/pose.py` is relative to a package's src/ dir, not the repo root —
    # unresolvable without knowing which package, so deliberately left unchecked
    # rather than mis-flagged as missing.
    body = ["See `mavlink/pose.py::PoseSource` for the seam."]
    assert cited_path_findings(body, tmp_path) == []


def test_glob_and_template_tokens_are_not_flagged(tmp_path: Path) -> None:
    body = [
        "Run `packages/meshsa/tests/test_command_*.py`.",
        "New bundles live at `openspec/changes/<bundle>/tasks.md`.",
        "Covers `packages/jetson_yolo_gcs/src/jetson_yolo_gcs/mavlink/{pose,timesync}.py`.",
    ]
    assert cited_path_findings(body, tmp_path) == []


def test_prose_with_slashes_is_not_flagged(tmp_path: Path) -> None:
    body = ["The four signals are `rx/tx/forwarded/dropped/reconnects`."]
    assert cited_path_findings(body, tmp_path) == []


def test_duplicate_citations_report_once(tmp_path: Path) -> None:
    body = [
        "See `docs/missing.md`.",
        "Also see `docs/missing.md` again.",
    ]
    assert cited_path_findings(body, tmp_path) == ["docs/missing.md"]


def test_no_frontmatter_at_all_fails(skills_dir: Path, tmp_path: Path) -> None:
    write_skill(skills_dir, "alpha", content="# Just a heading, no frontmatter fence.\n")
    findings = validate_skills(skills_dir, tmp_path)
    assert any("frontmatter missing or malformed" in f for f in findings)


def test_malformed_frontmatter_line_fails(skills_dir: Path, tmp_path: Path) -> None:
    content = "---\nname alpha\n---\n\n## Procedure\n\nDo it.\n"  # no colon after "name"
    write_skill(skills_dir, "alpha", content=content)
    findings = validate_skills(skills_dir, tmp_path)
    assert any("frontmatter missing or malformed" in f for f in findings)


def test_unclosed_frontmatter_fence_fails(skills_dir: Path, tmp_path: Path) -> None:
    # Every line is well-formed `key: value`, but the closing `---` fence never
    # appears — a distinct failure mode from an actively malformed line.
    content = '---\nname: alpha\ndescription: "Use when: x"\nargument-hint: "x"\n'
    write_skill(skills_dir, "alpha", content=content)
    findings = validate_skills(skills_dir, tmp_path)
    assert any("frontmatter missing or malformed" in f for f in findings)
    # No closing fence also means no body headings can be found.
    assert any("fewer than 1 '## ' section heading" in f for f in findings)


def test_frontmatter_comment_and_blank_lines_are_skipped(skills_dir: Path, tmp_path: Path) -> None:
    content = (
        "---\n"
        "# a frontmatter comment\n"
        "\n"
        "name: alpha\n"
        'description: "Use when: x"\n'
        'argument-hint: "x"\n'
        "---\n\n## Procedure\n\nDo it.\n"
    )
    write_skill(skills_dir, "alpha", content=content)
    assert validate_skills(skills_dir, tmp_path) == []


def test_cited_missing_path_surfaces_through_validate_file(
    skills_dir: Path, tmp_path: Path
) -> None:
    content = VALID_TEMPLATE.format(name="alpha") + "\nSee `docs/does-not-exist.md`.\n"
    write_skill(skills_dir, "alpha", content=content)
    findings = validate_skills(skills_dir, tmp_path)
    assert any("cited path does not exist in repo: docs/does-not-exist.md" in f for f in findings)


def test_repo_root_uses_env_var_when_set(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    assert vs.repo_root() == tmp_path.resolve()


def test_repo_root_falls_back_to_script_parent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    assert vs.repo_root() == Path(vs.__file__).resolve().parent.parent


def test_real_skills_pass_via_cli() -> None:
    """Integration: the committed .agents/skills roster must be clean."""
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(REPO_ROOT)}
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "tools" / "validate_skills.py")],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.startswith("OK: 12 skill file(s)")
