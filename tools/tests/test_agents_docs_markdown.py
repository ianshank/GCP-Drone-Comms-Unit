"""Tests for ``tools/agents_docs/markdown.py`` and the shared extraction primitives."""

from __future__ import annotations

import pytest

from tools.agents_docs import (
    is_checkable_guide_token,
    is_normative_heading,
    iter_bullets,
    iter_normative_bullets,
    iter_sections,
)
from tools.validate_skills import ORIGIN_BACKTICK, ORIGIN_LINK, is_path_shaped, iter_raw_path_tokens

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
