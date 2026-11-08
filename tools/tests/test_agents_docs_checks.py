"""Tests for checks 1–7 of ``tools/agents_docs/checks.py`` against synthetic files."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.agents_docs import (
    check_cited_paths,
    check_control_characters,
    check_manifest,
    check_normative_section_present,
    check_required_sections,
    check_rule_rationale,
    check_security_control_tag,
    policy,
    resolution_bases,
)
from tools.tests.conftest import CLEAN_GUIDE, git, write

# ---- check 1: manifest -------------------------------------------------------


def test_manifest_clean(repo: Path, one_guide_manifest: None) -> None:
    write(repo, "AGENTS.md", CLEAN_GUIDE)
    git(repo, "add", "AGENTS.md")
    assert check_manifest(repo) == []


def test_manifest_flags_tracked_guide_not_declared(repo: Path, one_guide_manifest: None) -> None:
    write(repo, "AGENTS.md", CLEAN_GUIDE)
    write(repo, "extra/AGENTS.md", CLEAN_GUIDE)
    git(repo, "add", "AGENTS.md", "extra/AGENTS.md")
    findings = check_manifest(repo)
    assert any("extra/AGENTS.md: tracked AGENTS.md is not in GUIDE_MANIFEST" in f for f in findings)


def test_manifest_flags_declared_guide_not_tracked(repo: Path, one_guide_manifest: None) -> None:
    """An untracked guide still loads in the harness but never reaches review."""
    write(repo, "AGENTS.md", CLEAN_GUIDE)  # written, never `git add`ed
    findings = check_manifest(repo)
    assert any("AGENTS.md: in GUIDE_MANIFEST but not tracked by git" in f for f in findings)


# ---- check 2: required sections ---------------------------------------------


def test_missing_traps_section_flagged() -> None:
    lines = CLEAN_GUIDE.replace("## Traps", "## Something Else").splitlines()
    findings = check_required_sections("AGENTS.md", lines)
    assert findings == ["AGENTS.md: missing required section '## Traps'"]


def test_present_traps_section_passes() -> None:
    assert check_required_sections("AGENTS.md", CLEAN_GUIDE.splitlines()) == []


# ---- check 3: cited paths ----------------------------------------------------


def test_unresolved_citation_flagged(tmp_path: Path) -> None:
    findings = check_cited_paths("AGENTS.md", "See `docs/nope.md`.", tmp_path)
    assert findings == ["AGENTS.md: cited path does not resolve: docs/nope.md"]


def test_citation_resolving_from_repo_root_passes(tmp_path: Path) -> None:
    write(tmp_path, "docs/real.md", "x")
    assert check_cited_paths("AGENTS.md", "See `docs/real.md`.", tmp_path) == []


def test_citation_resolving_from_guide_own_directory_passes(tmp_path: Path) -> None:
    """`ops/AGENTS.md` citing `[base-service](base-service)` resolves beside itself."""
    write(tmp_path, "ops/base-service/README.md", "x")
    assert check_cited_paths("ops/AGENTS.md", "See [base-service](base-service).", tmp_path) == []


def test_citation_resolving_via_package_source_root_passes(tmp_path: Path) -> None:
    """The third base: `detection/factory.py` under `<guide dir>/src/<pkg>/`."""
    write(tmp_path, "packages/p/src/p/detection/factory.py", "x")
    text = "The seam is `detection/factory.py`."
    assert check_cited_paths("packages/p/AGENTS.md", text, tmp_path) == []


def test_resolution_bases_include_each_package_source_root(tmp_path: Path) -> None:
    write(tmp_path, "packages/p/src/p/__init__.py", "")
    bases = resolution_bases("packages/p/AGENTS.md", tmp_path)
    assert bases[0] == tmp_path / "packages" / "p"
    assert tmp_path / "packages" / "p" / "src" / "p" in bases
    assert bases[-1] == tmp_path


def test_duplicate_citations_report_once(tmp_path: Path) -> None:
    text = "See `docs/nope.md`. Again: `docs/nope.md`."
    assert len(check_cited_paths("AGENTS.md", text, tmp_path)) == 1


def test_citation_exception_suppresses_finding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        policy,
        "CITATION_EXCEPTIONS",
        {"AGENTS.md": {"docs/nope.md": "named to explain why it cannot exist"}},
    )
    assert check_cited_paths("AGENTS.md", "See `docs/nope.md`.", tmp_path) == []


def test_citation_exception_without_rationale_is_itself_a_finding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(policy, "CITATION_EXCEPTIONS", {"AGENTS.md": {"docs/nope.md": "   "}})
    findings = check_cited_paths("AGENTS.md", "See `docs/nope.md`.", tmp_path)
    assert findings == ["AGENTS.md: citation exception for 'docs/nope.md' has an empty rationale"]


def test_root_only_link_target_is_reported_as_dead_from_the_file(tmp_path: Path) -> None:
    """A link that resolves only from the repo root is dead for every renderer."""
    write(tmp_path, "docs/real.md", "x")
    findings = check_cited_paths(".claude/rules/r.md", "See [real](docs/real.md).", tmp_path)
    assert findings == [
        ".claude/rules/r.md: link target resolves only from the repo root, so it is dead "
        "when followed from rules/ — make it relative: docs/real.md"
    ]


# ---- check 4: control characters ---------------------------------------------


@pytest.mark.parametrize(
    "char",
    [
        "‮",  # bidi override — the classic "rules-file backdoor"
        "​",  # zero-width space
        "⁦",  # bidi isolate
        "﻿",  # BOM
        "⁠",  # word joiner
        "­",  # soft hyphen
        "\U000e0041",  # Tags block "A" — invisible ASCII, the primary smuggling form
        "️",  # variation selector
    ],
)
def test_forbidden_code_points_flagged(char: str) -> None:
    findings = check_control_characters("AGENTS.md", f"safe{char}text")
    assert len(findings) == 1
    assert f"U+{ord(char):04X}" in findings[0]
    assert "at offset 4" in findings[0]


def test_mandated_punctuation_is_not_flagged() -> None:
    """The authoring contract mandates U+2014 and U+00B7; neither may trip the check.

    This is the reason the check is an explicit deny-list of non-rendering code points
    rather than a density or "ASCII-dominant" threshold: any threshold would fire on
    the format the contract itself requires.
    """
    assert check_control_characters("AGENTS.md", "a — b · c ≤ d") == []


def test_tags_block_is_covered_end_to_end() -> None:
    """The whole Tags block, not just a sample: it is the primary smuggling encoding."""
    missing = [cp for cp in range(0xE0000, 0xE0080) if chr(cp) not in policy.FORBIDDEN_CODE_POINTS]
    assert missing == []


# ---- check 5: a check that would otherwise go quiet --------------------------


def test_guide_without_normative_section_is_flagged() -> None:
    """Regression guard: the rule checks are heading-scoped, so they must fail closed.

    Written against the literal heading ``Rules``, checks 6 and 7 inspected two of the
    five committed guides and reported a clean pass for the other three — including the
    root guide, where the security-relevant rules are.
    """
    lines = ["# Guide", "", "## Traps", "", "- something"]
    findings = check_normative_section_present("AGENTS.md", lines)
    assert len(findings) == 1
    assert "no normative section found" in findings[0]


def test_guide_with_renamed_but_recognised_section_passes() -> None:
    lines = ["## Engineering Rules", "- alpha — why: reason"]
    assert check_normative_section_present("AGENTS.md", lines) == []


# ---- check 6: rationale ------------------------------------------------------


def test_rule_without_rationale_flagged() -> None:
    lines = ["## Rules", "- Keep changes scoped."]
    findings = check_rule_rationale("AGENTS.md", lines)
    assert len(findings) == 1
    assert "rule has no 'why:' clause" in findings[0]


def test_rule_with_rationale_passes() -> None:
    lines = ["## Rules", "- Keep changes scoped — why: a wide diff hides the one line."]
    assert check_rule_rationale("AGENTS.md", lines) == []


def test_rationale_on_a_continuation_line_passes() -> None:
    """The fold in iter_bullets is what makes a wrapped rule readable to the check."""
    lines = ["## Rules", "- Keep changes scoped", "  — why: a wide diff hides the one line."]
    assert check_rule_rationale("AGENTS.md", lines) == []


def test_bullets_outside_normative_sections_need_no_rationale() -> None:
    lines = ["## Commands", "- Run the tests."]
    assert check_rule_rationale("AGENTS.md", lines) == []


def test_long_rule_is_excerpted_in_the_finding() -> None:
    lines = ["## Rules", "- " + "x" * 100]
    [finding] = check_rule_rationale("AGENTS.md", lines)
    assert finding.endswith("...")
    assert len(finding.split(": ")[-1]) == 63  # 60 characters + the ellipsis


# ---- check 7: security control tag -------------------------------------------


def test_security_rule_without_control_flagged() -> None:
    lines = ["## Rules", "- Never commit secrets — why: a leaked key cannot be rotated."]
    findings = check_security_control_tag("AGENTS.md", lines)
    assert len(findings) == 1
    assert "names no enforcing control" in findings[0]


@pytest.mark.parametrize("tag", ["control: literal_guard", "advisory"])
def test_security_rule_with_disclosure_passes(tag: str) -> None:
    lines = ["## Rules", f"- Never commit secrets — why: keys cannot be rotated — {tag}."]
    assert check_security_control_tag("AGENTS.md", lines) == []


def test_non_security_rule_needs_no_control() -> None:
    lines = ["## Rules", "- Keep changes scoped — why: a wide diff hides the one line."]
    assert check_security_control_tag("AGENTS.md", lines) == []
