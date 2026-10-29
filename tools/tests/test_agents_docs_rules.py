"""Tests for checks 8–9 (rule frontmatter and scope) and the glob machinery of ``tools/agents_docs``."""

from __future__ import annotations

import pytest

from tools.agents_docs import (
    check_rule_frontmatter,
    check_rule_scope_matches,
    glob_matches,
    glob_to_regex,
    policy,
    rule_globs,
)

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


def test_rule_with_unrelated_keys_only_is_flagged_generically() -> None:
    findings = check_rule_frontmatter("r.md", ["---", "title: x", "---"])
    assert findings == [
        "r.md: frontmatter declares no 'paths' key, so this rule loads in every session "
        "rather than when a matching file is opened"
    ]


def test_rule_with_paths_key_passes() -> None:
    assert check_rule_frontmatter("r.md", ["---", "paths:", "  - 'src/**'", "---"]) == []


def test_rule_with_empty_paths_key_is_flagged() -> None:
    """`paths:` with nothing under it leaves the rule with no effective scope.

    It is neither path-scoped nor a declared ambient rule, and the scope check below
    cannot see it either — there are no patterns to call dead.
    """
    findings = check_rule_frontmatter("r.md", ["---", "paths:", "---"])
    assert len(findings) == 1
    assert "no effective scope" in findings[0]


def test_declared_ambient_rule_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    """A rule may be deliberately always-on, but it has to say so."""
    monkeypatch.setattr(policy, "AMBIENT_RULE_EXCEPTIONS", {"r.md": "always-on by design"})
    assert check_rule_frontmatter("r.md", ["## Rules", "- a — why: b"]) == []


def test_ambient_rule_exception_requires_a_rationale(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(policy, "AMBIENT_RULE_EXCEPTIONS", {"r.md": "  "})
    findings = check_rule_frontmatter("r.md", ["## Rules", "- a — why: b"])
    assert findings == ["r.md: ambient-rule exception has an empty rationale"]


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
        ("src/?.py", "src/a.py"),  # ? matches one non-separator character
        ("src/{a,{b,c}}.py", "src/c.py"),  # nested braces expand recursively
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
        ("src/?.py", "src/ab.py"),
    ],
)
def test_glob_does_not_match(pattern: str, path: str) -> None:
    assert glob_matches(pattern, [path]) is False


def test_unbalanced_brace_is_matched_literally() -> None:
    assert glob_to_regex("src/{a.py").match("src/{a.py")


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
    monkeypatch.setattr(policy, "DEAD_GLOB_EXCEPTIONS", {"r.md": {"lib/**/*.tsx": "planned"}})
    assert check_rule_scope_matches("r.md", lines, []) == []
    monkeypatch.setattr(policy, "DEAD_GLOB_EXCEPTIONS", {"r.md": {"lib/**/*.tsx": "  "}})
    findings = check_rule_scope_matches("r.md", lines, [])
    assert findings == ["r.md: dead-glob exception for 'lib/**/*.tsx' has an empty rationale"]


def test_rule_globs_reads_both_documented_spellings() -> None:
    """`paths:` takes a YAML list or a single comma-separated string."""
    as_list = ["---", "paths:", '  - "a/**"', '  - "b/**"', "---"]
    as_string = ["---", 'paths: "a/**, b/**"', "---"]
    assert rule_globs(as_list) == ["a/**", "b/**"]
    assert rule_globs(as_string) == ["a/**", "b/**"]


def test_rule_globs_without_frontmatter_or_unclosed_is_empty() -> None:
    assert rule_globs(["## Rules"]) == []
    assert rule_globs(["---", "paths:", "  - 'x'"]) == []
    assert rule_globs([]) == []
