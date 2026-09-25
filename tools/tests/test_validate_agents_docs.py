"""Tests for tools/validate_agents_docs.py against synthetic and real instruction files.

Synthetic cases build a throwaway git work tree under ``tmp_path`` rather than
stubbing ``git ls-files``, so the enumeration path this linter depends on is the one
under test. The real-corpus cases at the end assert the committed guides stay clean on
the checks that already hold today.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

import tools.validate_agents_docs as vad
from tools.validate_agents_docs import (
    check_cited_paths,
    check_control_characters,
    check_manifest,
    check_normative_section_present,
    check_required_sections,
    check_rule_frontmatter,
    check_rule_rationale,
    check_rule_scope_matches,
    check_security_control_tag,
    glob_matches,
    is_checkable_guide_token,
    is_normative_heading,
    iter_bullets,
    iter_normative_bullets,
    iter_sections,
    main,
    resolution_bases,
    rule_globs,
    validate_file,
    validate_instruction_files,
)
from tools.validate_skills import ORIGIN_BACKTICK, ORIGIN_LINK, is_path_shaped, iter_raw_path_tokens

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
    monkeypatch.setattr(vad, "GUIDE_MANIFEST", ("AGENTS.md",))


# ---- shared extraction primitives -------------------------------------------


@pytest.mark.parametrize(
    "token",
    ["docs/<slug>.md", "https://example.com/x", "/metrics", ".onnx", ""],
)
def test_is_path_shaped_rejects_non_paths(token: str) -> None:
    assert is_path_shaped(token) is False


@pytest.mark.parametrize("token", ["docs/real.md", "../AGENTS.md", "base-service"])
def test_is_path_shaped_accepts_path_shaped(token: str) -> None:
    assert is_path_shaped(token) is True


def test_iter_raw_path_tokens_tags_origin() -> None:
    text = "See `docs/a.md` and [b](docs/b.md)."
    assert list(iter_raw_path_tokens(text, include_link_targets=True)) == [
        ("docs/a.md", ORIGIN_BACKTICK),
        ("docs/b.md", ORIGIN_LINK),
    ]


def test_iter_raw_path_tokens_omits_links_by_default() -> None:
    """The skills linter's contract: backticks only unless link targets are asked for."""
    text = "See `docs/a.md` and [b](docs/b.md)."
    assert list(iter_raw_path_tokens(text)) == [("docs/a.md", ORIGIN_BACKTICK)]


@pytest.mark.parametrize(
    ("token", "origin"),
    [
        ("docs/real.md", ORIGIN_BACKTICK),  # repo-root-relative, as skills are checked
        ("../AGENTS.md", ORIGIN_BACKTICK),  # explicit relative prefix
        ("./sibling.md", ORIGIN_BACKTICK),
        ("base-service", ORIGIN_LINK),  # a link target is a path claim by construction
    ],
)
def test_guide_token_accepted(token: str, origin: str) -> None:
    assert is_checkable_guide_token(token, origin) is True


@pytest.mark.parametrize(
    ("token", "origin"),
    [
        ("SIGINT", ORIGIN_BACKTICK),  # prose in backticks, not a path
        ("meshsa-base", ORIGIN_BACKTICK),  # a console-script name
        ("https://example.com", ORIGIN_LINK),  # a URL, not a repo path
        ("/metrics", ORIGIN_LINK),  # an HTTP route
    ],
)
def test_guide_token_rejected(token: str, origin: str) -> None:
    assert is_checkable_guide_token(token, origin) is False


# ---- markdown structure ------------------------------------------------------


def test_iter_sections_ignores_headings_inside_fences() -> None:
    lines = [
        "## Real",
        "text",
        "```",
        "## Not a heading",
        "```",
        "more",
    ]
    sections = list(iter_sections(lines))
    assert [heading for heading, _ in sections] == ["Real"]
    assert "## Not a heading" in sections[0][1]


def test_iter_bullets_folds_continuation_lines() -> None:
    body = ["- first rule", "  continued here", "", "- second rule"]
    assert list(iter_bullets(body)) == ["- first rule continued here", "- second rule"]


def test_iter_bullets_reads_ordered_list_items() -> None:
    """Regression guard: a normative section may number its rules.

    `packages/jetson_yolo_gcs/AGENTS.md` numbers its five conventions, and an
    unordered-only pattern left all five unchecked while the run stayed green.
    """
    body = ["1. first rule", "2. second rule"]
    assert list(iter_bullets(body)) == ["1. first rule", "2. second rule"]


def test_iter_bullets_treats_indented_items_as_continuations() -> None:
    """A nested sub-item belongs to its parent rule, not to a rule of its own."""
    body = ["- parent rule", "  - nested detail", "- next rule"]
    assert list(iter_bullets(body)) == ["- parent rule - nested detail", "- next rule"]


@pytest.mark.parametrize(
    "heading",
    ["Rules", "Engineering Rules", "Framework Rules", "Conventions (keep these invariant)"],
)
def test_normative_headings_recognised(heading: str) -> None:
    """Every spelling already in the tree qualifies without being enumerated."""
    assert is_normative_heading(heading) is True


@pytest.mark.parametrize("heading", ["Commands", "Verification", "Repository Map", "Scope"])
def test_non_normative_headings_rejected(heading: str) -> None:
    assert is_normative_heading(heading) is False


def test_normative_match_is_whole_word() -> None:
    """A keyword buried in a longer word must not promote a heading."""
    assert is_normative_heading("Overruled Decisions") is False


def test_iter_normative_bullets_spans_every_matching_section() -> None:
    lines = [
        "## Engineering Rules",
        "- alpha",
        "## Commands",
        "- not a rule",
        "## Conventions",
        "- beta",
    ]
    assert list(iter_normative_bullets(lines)) == ["- alpha", "- beta"]


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
        vad,
        "CITATION_EXCEPTIONS",
        {"AGENTS.md": {"docs/nope.md": "named to explain why it cannot exist"}},
    )
    assert check_cited_paths("AGENTS.md", "See `docs/nope.md`.", tmp_path) == []


def test_citation_exception_without_rationale_is_itself_a_finding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(vad, "CITATION_EXCEPTIONS", {"AGENTS.md": {"docs/nope.md": "   "}})
    findings = check_cited_paths("AGENTS.md", "See `docs/nope.md`.", tmp_path)
    assert findings == ["AGENTS.md: citation exception for 'docs/nope.md' has an empty rationale"]


# ---- check 4: control characters ---------------------------------------------


@pytest.mark.parametrize("char", ["‮", "​", "⁦", "﻿"])
def test_forbidden_code_points_flagged(char: str) -> None:
    findings = check_control_characters("AGENTS.md", f"safe{char}text")
    assert len(findings) == 1
    assert f"U+{ord(char):04X}" in findings[0]
    assert "at offset 4" in findings[0]


def test_mandated_punctuation_is_not_flagged() -> None:
    """The authoring contract mandates U+2014 and U+00B7; neither may trip the check."""
    assert check_control_characters("AGENTS.md", "a — b · c") == []


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


# ---- orchestration and CLI ---------------------------------------------------


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


# ---- check 8: rule frontmatter ----------------------------------------------


def test_rule_without_frontmatter_is_flagged() -> None:
    """The inverted failure: no frontmatter means the rule loads in every session."""
    findings = check_rule_frontmatter("r.md", ["## Rules", "- a — why: b"])
    assert len(findings) == 1
    assert "loads in every session" in findings[0]


def test_rule_with_unclosed_frontmatter_is_flagged() -> None:
    findings = check_rule_frontmatter("r.md", ["---", "paths:", "  - 'x'"])
    assert len(findings) == 1
    assert "never closed" in findings[0]


@pytest.mark.parametrize("bad_key", ["globs", "path", "appliesTo"])
def test_rule_with_misspelled_scope_key_names_it(bad_key: str) -> None:
    """A near-miss is reported by name: the generic message sends authors hunting."""
    findings = check_rule_frontmatter("r.md", ["---", f"{bad_key}:", "  - 'x'", "---"])
    assert len(findings) == 1
    assert bad_key.casefold() in findings[0]
    assert "loads in every session" in findings[0]


def test_rule_with_paths_key_passes() -> None:
    assert check_rule_frontmatter("r.md", ["---", "paths:", "  - 'src/**'", "---"]) == []


# ---- check 9: rule scope actually matches -----------------------------------


@pytest.mark.parametrize(
    ("pattern", "path"),
    [
        ("src/**/*.py", "src/pkg/mod.py"),
        ("src/**", "src/pkg/mod.py"),
        ("src/**", "src"),  # a trailing /** also covers the directory itself
        ("*.yaml", "top.yaml"),
        ("src/*.py", "src/mod.py"),
        ("src/**/*.{ts,tsx}", "src/a/b.tsx"),  # brace expansion
    ],
)
def test_glob_matches_live_patterns(pattern: str, path: str) -> None:
    assert glob_matches(pattern, [path]) is True


@pytest.mark.parametrize(
    ("pattern", "path"),
    [
        ("src/*.py", "src/pkg/mod.py"),  # a single * does not cross a separator
        ("lib/**/*.tsx", "artifacts/a/b.tsx"),  # the real dead glob this check found
        ("src/**/*.{ts,tsx}", "src/a/b.py"),
    ],
)
def test_glob_does_not_match(pattern: str, path: str) -> None:
    assert glob_matches(pattern, [path]) is False


def test_dead_glob_is_flagged() -> None:
    lines = ["---", "paths:", "  - 'lib/**/*.tsx'", "---"]
    findings = check_rule_scope_matches("r.md", lines, ["artifacts/a/b.tsx"])
    assert len(findings) == 1
    assert "never fires" in findings[0]


def test_live_glob_passes() -> None:
    lines = ["---", "paths:", "  - 'lib/**/*.ts'", "---"]
    assert check_rule_scope_matches("r.md", lines, ["lib/a/b.ts"]) == []


def test_dead_glob_exception_requires_a_rationale(monkeypatch: pytest.MonkeyPatch) -> None:
    lines = ["---", "paths:", "  - 'lib/**/*.tsx'", "---"]
    monkeypatch.setattr(vad, "DEAD_GLOB_EXCEPTIONS", {"r.md": {"lib/**/*.tsx": "planned"}})
    assert check_rule_scope_matches("r.md", lines, []) == []
    monkeypatch.setattr(vad, "DEAD_GLOB_EXCEPTIONS", {"r.md": {"lib/**/*.tsx": "  "}})
    findings = check_rule_scope_matches("r.md", lines, [])
    assert findings == ["r.md: dead-glob exception for 'lib/**/*.tsx' has an empty rationale"]


def test_rule_globs_reads_both_documented_spellings() -> None:
    """`paths:` takes a YAML list or a single comma-separated string."""
    as_list = ["---", "paths:", '  - "a/**"', '  - "b/**"', "---"]
    as_string = ["---", 'paths: "a/**, b/**"', "---"]
    assert rule_globs(as_list) == ["a/**", "b/**"]
    assert rule_globs(as_string) == ["a/**", "b/**"]


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


# ---- real corpus -------------------------------------------------------------


def test_real_guides_match_the_manifest() -> None:
    assert check_manifest(REPO_ROOT) == []


@pytest.mark.parametrize("rel_path", vad.GUIDE_MANIFEST)
def test_real_guide_citations_all_resolve(rel_path: str) -> None:
    text = (REPO_ROOT / rel_path).read_text(encoding="utf-8")
    assert check_cited_paths(rel_path, text, REPO_ROOT) == []


@pytest.mark.parametrize("rel_path", vad.GUIDE_MANIFEST)
def test_real_guide_has_no_hidden_code_points(rel_path: str) -> None:
    text = (REPO_ROOT / rel_path).read_text(encoding="utf-8")
    assert check_control_characters(rel_path, text) == []


@pytest.mark.parametrize("rel_path", vad.GUIDE_MANIFEST)
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
    expected_count = len(vad.GUIDE_MANIFEST) + len(vad.discovered_rules(REPO_ROOT))
    assert result.stdout.startswith(f"OK: {expected_count} instruction file(s)")
