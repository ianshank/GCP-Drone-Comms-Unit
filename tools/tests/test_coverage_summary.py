"""Tests for ``tools/coverage_summary.py`` (plan P3-2, D3)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.coverage_summary import main, summarize

_XML = (
    '<?xml version="1.0" ?>\n'
    '<coverage line-rate="0.9939" branch-rate="0.9712" branches-valid="1104"></coverage>\n'
)
_XML_NO_BRANCHES = (
    '<?xml version="1.0" ?>\n'
    '<coverage line-rate="0.9651" branch-rate="0" branches-valid="0"></coverage>\n'
)


def test_summarize_reports_rates_against_the_gate(tmp_path: Path) -> None:
    xml = tmp_path / "coverage.xml"
    xml.write_text(_XML, encoding="utf-8")
    assert summarize("meshsa", 97, xml) == (
        "**meshsa coverage**: 99.39% lines, 97.12% branches (gate: 97%)"
    )


def test_summarize_explains_a_missing_file_instead_of_failing(tmp_path: Path) -> None:
    line = summarize("tools", 90, tmp_path / "coverage.xml")
    assert line.startswith("**tools coverage**: coverage.xml not produced")


def test_main_prints_the_line_and_always_exits_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["jetson", "96", "--xml", str(tmp_path / "missing.xml")]) == 0
    assert "missing.xml not produced" in capsys.readouterr().out
    xml = tmp_path / "coverage.xml"
    xml.write_text(_XML, encoding="utf-8")
    assert main(["jetson", "96", "--xml", str(xml)]) == 0
    assert capsys.readouterr().out.strip() == (
        "**jetson coverage**: 99.39% lines, 97.12% branches (gate: 96%)"
    )


def test_summarize_omits_branches_when_branch_coverage_was_not_measured(tmp_path: Path) -> None:
    """The tools job runs without --cov-branch; a literal 0.00% would read as a measurement."""
    xml = tmp_path / "coverage.xml"
    xml.write_text(_XML_NO_BRANCHES, encoding="utf-8")
    assert summarize("tools", 90, xml) == "**tools coverage**: 96.51% lines (gate: 90%)"
