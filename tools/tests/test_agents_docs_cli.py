"""Tests for the orchestration, advisory sweep and CLI of ``tools/agents_docs``, and the real corpus."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tools.agents_docs import (
    check_cited_paths,
    check_control_characters,
    check_docs_citations,
    check_manifest,
    check_normative_section_present,
    discovered_context_files,
    discovered_rules,
    docs_citation_targets,
    iter_normative_bullets,
    main,
    matches_single_level_glob,
    policy,
    resolution_bases,
    tracked_files,
    validate_file,
    validate_instruction_files,
)
from tools.tests.conftest import CLEAN_GUIDE, CLEAN_RULE, REPO_ROOT, git, write

# ---- orchestration -----------------------------------------------------------


def test_validate_file_reports_a_missing_file(tmp_path: Path) -> None:
    assert validate_file("AGENTS.md", tmp_path, require_sections=True) == [
        "AGENTS.md: file does not exist"
    ]


def test_clean_synthetic_repo_passes(repo: Path, one_guide_manifest: None) -> None:
    write(repo, "AGENTS.md", CLEAN_GUIDE)
    git(repo, "add", "AGENTS.md")
    assert validate_instruction_files(repo) == []
    assert main(["--root", str(repo)]) == 0


def test_rules_files_are_validated_too(repo: Path, one_guide_manifest: None) -> None:
    """`.claude/rules/*.md` is discovered, not allowlisted, and shares the rule checks."""
    write(repo, "AGENTS.md", CLEAN_GUIDE)
    write(repo, "src/a.py", "x = 1\n")
    git(repo, "add", "AGENTS.md", "src/a.py")
    write(repo, ".claude/rules/example.md", CLEAN_RULE.replace(" — why: a reason.", "."))
    findings = validate_instruction_files(repo)
    assert any(".claude/rules/example.md: rule has no 'why:' clause" in f for f in findings)


def test_rules_file_needs_no_traps_section(repo: Path, one_guide_manifest: None) -> None:
    """Required sections are a guide obligation; a rules file is scoped, not an overview."""
    write(repo, "AGENTS.md", CLEAN_GUIDE)
    write(repo, "src/a.py", "x = 1\n")
    git(repo, "add", "AGENTS.md", "src/a.py")
    write(repo, ".claude/rules/example.md", CLEAN_RULE)
    assert validate_instruction_files(repo) == []


def test_context_files_tracked_but_missing_from_the_work_tree_are_skipped(
    repo: Path, one_guide_manifest: None
) -> None:
    write(repo, "AGENTS.md", CLEAN_GUIDE)
    write(repo, "CLAUDE.md", "@AGENTS.md\n")
    git(repo, "add", ".")
    (repo / "CLAUDE.md").unlink()  # still in the index, gone from the work tree
    assert validate_instruction_files(repo) == []


# ---- CLI ---------------------------------------------------------------------


def test_main_reports_findings_and_exits_one(
    repo: Path, one_guide_manifest: None, capsys: pytest.CaptureFixture[str]
) -> None:
    write(repo, "AGENTS.md", "# Guide\n\n## Rules\n\n- Unexplained rule.\n")
    git(repo, "add", "AGENTS.md")
    assert main(["--root", str(repo)]) == 1
    out = capsys.readouterr().out
    assert "missing required section '## Traps'" in out
    assert out.rstrip().endswith("finding(s) across the instruction files under " + str(repo))


def test_main_exits_two_outside_a_git_work_tree(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An operational failure is reported distinctly from a policy finding."""
    assert main(["--root", str(tmp_path)]) == 2
    assert "is not a git work tree" in capsys.readouterr().out


def test_verbose_flag_emits_a_debug_trace(
    repo: Path, one_guide_manifest: None, caplog: pytest.LogCaptureFixture
) -> None:
    write(repo, "AGENTS.md", CLEAN_GUIDE)
    git(repo, "add", "AGENTS.md")
    with caplog.at_level("DEBUG", logger="validate_agents_docs"):
        assert main(["--root", str(repo), "--verbose"]) == 0
    assert any("validating AGENTS.md" in record.getMessage() for record in caplog.records)


# ---- docs citation sweep (plan P1-3 advisory -> P3-3 gating) -------------------


def test_docs_citations_report_dead_paths_in_stable_docs_only(repo: Path) -> None:
    write(repo, "README.md", "See `docs/CHARTER.md` and `docs/missing.md`.\n")
    write(repo, "docs/CHARTER.md", "Cites [NEXTSTEPS.md](NEXTSTEPS.md) relative to docs/.\n")
    write(repo, "docs/NEXTSTEPS.md", "Backlog.\n")
    write(repo, "docs/reviews/OLD.md", "Historical: `tools/gone.py`.\n")
    git(repo, "add", ".")
    tracked = tracked_files(repo)
    # README's dead citation is reported; the live one is not; docs/CHARTER.md's link
    # resolves relative to its own directory; docs/reviews/ is outside the sweep.
    assert check_docs_citations(repo, tracked) == [
        "README.md: cited path does not resolve: docs/missing.md"
    ]
    assert docs_citation_targets(tracked) == ["README.md", "docs/CHARTER.md", "docs/NEXTSTEPS.md"]


def test_a_dead_docs_citation_fails_the_run(
    repo: Path, one_guide_manifest: None, capsys: pytest.CaptureFixture[str]
) -> None:
    """Gating since P3-3: the finding is printed and counted like a guide's."""
    write(repo, "AGENTS.md", CLEAN_GUIDE)
    write(repo, "README.md", "Dead: `docs/missing.md`.\n")
    git(repo, "add", ".")
    assert main(["--root", str(repo)]) == 1
    out = capsys.readouterr().out
    assert "README.md: cited path does not resolve: docs/missing.md" in out
    assert "::warning" not in out
    assert out.rstrip().endswith(
        "FAIL: 1 finding(s) across the instruction files under " + str(repo)
    )


def test_docs_citations_skip_tracked_paths_missing_from_the_work_tree(repo: Path) -> None:
    write(repo, "README.md", "Dead: `docs/missing.md`.\n")
    write(repo, "docs/CHARTER.md", "Also dead: `docs/missing.md`.\n")
    git(repo, "add", ".")
    (repo / "docs" / "CHARTER.md").unlink()  # still in the index, gone from the work tree
    assert check_docs_citations(repo, tracked_files(repo)) == [
        "README.md: cited path does not resolve: docs/missing.md"
    ]


@pytest.mark.parametrize("doc", ["docs/specs/x.md", "docs/architecture/x.md", "docs/adr/x.md"])
def test_docs_sweep_reaches_every_stable_docs_subtree(repo: Path, doc: str) -> None:
    write(repo, doc, "Dead: `tools/gone.py`.\n")
    git(repo, "add", ".")
    assert check_docs_citations(repo, tracked_files(repo)) == [
        f"{doc}: cited path does not resolve: tools/gone.py"
    ]


def test_docs_findings_are_counted_with_instruction_findings(
    repo: Path, one_guide_manifest: None, capsys: pytest.CaptureFixture[str]
) -> None:
    write(repo, "AGENTS.md", "# Guide\n\n## Rules\n\n- Unexplained rule.\n")
    write(repo, "README.md", "Dead: `docs/missing.md`.\n")
    git(repo, "add", ".")
    assert main(["--root", str(repo)]) == 1
    lines = capsys.readouterr().out.splitlines()
    assert any("missing required section" in line for line in lines)
    assert any("docs/missing.md" in line for line in lines)
    assert lines[-1].startswith("FAIL: 3 ")  # 2 guide findings + 1 docs finding


def test_clean_docs_are_counted_in_the_verdict(
    repo: Path, one_guide_manifest: None, capsys: pytest.CaptureFixture[str]
) -> None:
    write(repo, "AGENTS.md", CLEAN_GUIDE)
    write(repo, "README.md", "Live: `AGENTS.md`.\n")
    git(repo, "add", ".")
    assert main(["--root", str(repo)]) == 0
    assert "1 doc(s) checked for dead citations)" in capsys.readouterr().out


def test_docs_citation_exception_suppresses_the_gating_finding(
    repo: Path,
    one_guide_manifest: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A planned path a spec must name is declared, with a rationale, like a guide's."""
    write(repo, "AGENTS.md", CLEAN_GUIDE)
    write(repo, "docs/specs/x.md", "Will live at `packages/planned_pkg`.\n")
    git(repo, "add", ".")
    monkeypatch.setattr(
        policy, "CITATION_EXCEPTIONS", {"docs/specs/x.md": {"packages/planned_pkg": "planned"}}
    )
    assert check_docs_citations(repo, tracked_files(repo)) == []
    assert main(["--root", str(repo)]) == 0
    monkeypatch.setattr(
        policy, "CITATION_EXCEPTIONS", {"docs/specs/x.md": {"packages/planned_pkg": "  "}}
    )
    assert main(["--root", str(repo)]) == 1  # an empty rationale is counted in the gating path
    assert "has an empty rationale" in capsys.readouterr().out


def test_real_citation_exceptions_are_live() -> None:
    """Every declared exception names a tracked, swept file, a token it contains, and a path
    that really does not resolve — so when a planned package lands, the entry is noticed."""
    tracked = set(tracked_files(REPO_ROOT))
    swept = set(docs_citation_targets(sorted(tracked))) | set(policy.GUIDE_MANIFEST)
    assert policy.CITATION_EXCEPTIONS, "the table is expected to carry the planned-path entries"
    for rel_path, tokens in policy.CITATION_EXCEPTIONS.items():
        assert rel_path in tracked, rel_path
        assert rel_path in swept, f"{rel_path} is not reached by any citation check"
        text = (REPO_ROOT / rel_path).read_text(encoding="utf-8")
        for token, rationale in tokens.items():
            assert token in text, f"{rel_path}: exception for a token it no longer cites: {token}"
            assert rationale.strip(), f"{rel_path}: {token} has an empty rationale"
            assert not any(
                (base / token).exists() for base in resolution_bases(rel_path, REPO_ROOT)
            ), f"{rel_path}: {token} now resolves; the exception is dead weight"


@pytest.mark.parametrize(
    ("rel_path", "pattern", "expected"),
    [
        ("docs/a.md", "docs/*.md", True),
        ("docs/reviews/a.md", "docs/*.md", False),
        ("docs/a.md", "docs/specs/*.md", False),
        ("README.md", "README.md", True),
        ("docs/specs/x.md", "docs/specs/*.md", True),
        ("docs/adr/x.md", "docs/adr/*.md", True),
    ],
)
def test_single_level_glob(rel_path: str, pattern: str, expected: bool) -> None:
    assert matches_single_level_glob(rel_path, pattern) is expected


# ---- real corpus -------------------------------------------------------------


def test_real_guides_match_the_manifest() -> None:
    assert check_manifest(REPO_ROOT) == []


@pytest.mark.parametrize("rel_path", policy.GUIDE_MANIFEST)
def test_real_guide_citations_all_resolve(rel_path: str) -> None:
    text = (REPO_ROOT / rel_path).read_text(encoding="utf-8")
    assert check_cited_paths(rel_path, text, REPO_ROOT) == []


@pytest.mark.parametrize("rel_path", policy.GUIDE_MANIFEST)
def test_real_guide_has_no_hidden_code_points(rel_path: str) -> None:
    text = (REPO_ROOT / rel_path).read_text(encoding="utf-8")
    assert check_control_characters(rel_path, text) == []


@pytest.mark.parametrize("rel_path", policy.GUIDE_MANIFEST)
def test_real_guide_rule_checks_are_not_vacuous(rel_path: str) -> None:
    """Every committed guide exposes its rules to checks 6 and 7.

    Asserted per guide rather than in aggregate: the bug this guards against hid in
    three of five files while the other two kept the run green.
    """
    lines = (REPO_ROOT / rel_path).read_text(encoding="utf-8").splitlines()
    assert check_normative_section_present(rel_path, lines) == []
    assert list(iter_normative_bullets(lines)), f"{rel_path}: normative section has no bullets"


def test_cli_runs_clean_against_the_real_repo() -> None:
    """Integration: the committed instruction files must stay clean.

    The count is derived, not written down: a hard-coded number would force every
    commit that adds a rules file to edit this literal, which is how a count-based
    assertion decays into a rubber stamp.
    """
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(REPO_ROOT)}
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "tools" / "validate_agents_docs.py")],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    expected_count = len(policy.GUIDE_MANIFEST) + len(discovered_rules(REPO_ROOT))
    verdict = result.stdout.splitlines()
    assert verdict and verdict[0].startswith(f"OK: {expected_count} instruction file(s)")
    assert "doc(s) checked for dead citations" in verdict[0]
    assert len(verdict) == 1  # the docs sweep gates (P3-3): no advisory lines precede it


def test_context_files_are_scanned_for_hidden_code_points() -> None:
    """CLAUDE.md and the skill/agent definitions are in the sweep's reach.

    They get the control-character check only — they are not guides — but the
    injection surface is identical, and neither sibling linter looks for hidden code
    points, so before this they passed the whole gate regardless of content.
    """
    context = discovered_context_files(REPO_ROOT, tracked_files(REPO_ROOT))
    assert "CLAUDE.md" in context
    assert any(p.startswith(".agents/skills/") for p in context)
    assert any(p.startswith(".claude/agents/") for p in context)
    for rel_path in context:
        text = (REPO_ROOT / rel_path).read_text(encoding="utf-8")
        assert check_control_characters(rel_path, text) == []
