"""The nine per-file checks of ``tools/agents_docs``, in the order the module docstring ranks them."""

from __future__ import annotations

import logging
from pathlib import Path

from tools.validate_skills import ORIGIN_LINK, iter_raw_path_tokens

from . import policy
from .markdown import (
    is_checkable_guide_token,
    is_normative_heading,
    iter_normative_bullets,
    iter_sections,
)
from .repo import glob_matches, resolution_bases, rule_globs, token_resolves, tracked_guides

logger = logging.getLogger("validate_agents_docs")


def check_manifest(root: Path) -> list[str]:
    """Check 1 — the tracked guide set and :data:`policy.GUIDE_MANIFEST` agree both ways."""
    tracked = set(tracked_guides(root))
    declared = set(policy.GUIDE_MANIFEST)
    findings = [
        f"{path}: tracked {policy.GUIDE_FILENAME} is not in GUIDE_MANIFEST "
        "(a new instruction file is a deliberate decision — add it or remove the file)"
        for path in sorted(tracked - declared)
    ]
    findings.extend(
        f"{path}: in GUIDE_MANIFEST but not tracked by git "
        "(never written, or untracked/ignored — the harness would load a file review never sees)"
        for path in sorted(declared - tracked)
    )
    return findings


def check_required_sections(rel_path: str, lines: list[str]) -> list[str]:
    """Check 2 — a guide carries every section in :data:`policy.REQUIRED_GUIDE_SECTIONS`."""
    present = {heading for heading, _ in iter_sections(lines)}
    return [
        f"{rel_path}: missing required section '{policy.HEADING_PREFIX}{name}'"
        for name in policy.REQUIRED_GUIDE_SECTIONS
        if name not in present
    ]


def check_cited_paths(rel_path: str, text: str, root: Path) -> list[str]:
    """Check 3 — every cited repo path resolves against one of its bases."""
    bases = resolution_bases(rel_path, root)
    allowed = policy.CITATION_EXCEPTIONS.get(rel_path, {})
    findings: list[str] = []
    seen: set[str] = set()
    for token, origin in iter_raw_path_tokens(text, include_link_targets=True):
        if token in seen or not is_checkable_guide_token(token, origin):
            continue
        seen.add(token)
        if token_resolves(token, bases):
            # A Markdown link is followed by a renderer relative to the file it is
            # written in, so resolving only via the repo-root fallback means the link
            # is dead for every human and every renderer — while the check that exists
            # to catch reference rot reports it clean. Caught five such links in the
            # first six `.claude/rules/*.md`, which are two directories deep.
            if (
                origin == ORIGIN_LINK
                and not token.startswith(policy.RELATIVE_PREFIXES)
                and not token_resolves(token, (bases[0],))
                and token not in allowed
            ):
                findings.append(
                    f"{rel_path}: link target resolves only from the repo root, so it is "
                    f"dead when followed from {bases[0].name or '.'}/ — make it relative: {token}"
                )
            continue
        if token in allowed:
            if not allowed[token].strip():
                findings.append(
                    f"{rel_path}: citation exception for {token!r} has an empty rationale"
                )
            else:
                logger.debug("%s: allowed counter-example citation %r", rel_path, token)
            continue
        findings.append(f"{rel_path}: cited path does not resolve: {token}")
    return findings


def check_control_characters(rel_path: str, text: str) -> list[str]:
    """Check 4 — no bidirectional-override or zero-width code points."""
    return [
        f"{rel_path}: forbidden control character U+{ord(char):04X} at offset {offset} "
        "(hidden-Unicode instruction-file payloads use these)"
        for offset, char in enumerate(text)
        if char in policy.FORBIDDEN_CODE_POINTS
    ]


def check_normative_section_present(rel_path: str, lines: list[str]) -> list[str]:
    """Check 5 — the guide has a section the rule checks can actually read.

    Without this, checks 6 and 7 are scoped by a heading match and so fail *open*:
    rename ``## Rules`` to something unrecognised and every rule beneath it stops
    being checked, while the run still reports a clean pass. A linter that goes
    quiet is worse than one that was never added, because the green line is taken
    as evidence. Turning that into a finding is the whole point of this check.
    """
    if any(is_normative_heading(heading) for heading, _ in iter_sections(lines)):
        return []
    return [
        f"{rel_path}: no normative section found — no '{policy.HEADING_PREFIX}' heading "
        f"contains any of {', '.join(policy.NORMATIVE_SECTION_KEYWORDS)}, so the rule checks "
        "below would silently inspect nothing"
    ]


def check_rule_rationale(rel_path: str, lines: list[str]) -> list[str]:
    """Check 6 — every rule records why it exists."""
    return [
        f"{rel_path}: rule has no '{policy.RATIONALE_MARKER}' clause "
        f"(an unexplained rule cannot be safely deleted later): {excerpt(bullet)}"
        for bullet in iter_normative_bullets(lines)
        if policy.RATIONALE_MARKER not in bullet.casefold()
    ]


def check_security_control_tag(rel_path: str, lines: list[str]) -> list[str]:
    """Check 7 — a security-relevant rule names its control, or is marked advisory."""
    findings: list[str] = []
    for bullet in iter_normative_bullets(lines):
        folded = bullet.casefold()
        if not any(keyword in folded for keyword in policy.SECURITY_KEYWORDS):
            continue
        if policy.CONTROL_MARKER in folded or policy.ADVISORY_MARKER in folded:
            continue
        findings.append(
            f"{rel_path}: security-relevant rule names no enforcing control "
            f"(add '{policy.CONTROL_MARKER} <name>' or '{policy.ADVISORY_MARKER}'): "
            f"{excerpt(bullet)}"
        )
    return findings


def check_rule_frontmatter(rel_path: str, lines: list[str]) -> list[str]:
    """Check 8 — a path-scoped rule actually declares its scope.

    Only the fences and the presence of the scoping key are checked, deliberately: the
    goal is to catch the inverted-failure case described on
    :data:`policy.RULES_FRONTMATTER_KEY`, not to re-implement a YAML parser. A rule that
    meant to be ambient can say so by carrying no frontmatter at all — that is a decision,
    whereas a misspelled key looks like scoping and is not.
    """
    if not lines or lines[0].strip() != policy.FRONTMATTER_FENCE:
        if rel_path in policy.AMBIENT_RULE_EXCEPTIONS:
            if not policy.AMBIENT_RULE_EXCEPTIONS[rel_path].strip():
                return [f"{rel_path}: ambient-rule exception has an empty rationale"]
            logger.debug("%s: declared ambient rule, no scope expected", rel_path)
            return []
        return [
            f"{rel_path}: no frontmatter block, so this rule loads in every session. "
            f"Add a '{policy.RULES_FRONTMATTER_KEY}:' key to scope it, or declare it in "
            "AMBIENT_RULE_EXCEPTIONS with a reason if it is meant to be always-on"
        ]
    try:
        close = lines.index(policy.FRONTMATTER_FENCE, 1)
    except ValueError:
        return [
            f"{rel_path}: frontmatter fence is never closed, so the block does not parse "
            "and the rule loads unconditionally"
        ]

    keys = {
        line.partition(":")[0].strip().casefold()
        for line in lines[1:close]
        if ":" in line and not line.startswith((" ", "\t", "-"))
    }
    if policy.RULES_FRONTMATTER_KEY in keys:
        if not rule_globs(lines):
            return [
                f"{rel_path}: '{policy.RULES_FRONTMATTER_KEY}' is declared but parses to no "
                "pattern, so the rule has no effective scope — it is neither path-scoped "
                "nor a declared ambient rule, and nothing else reports that"
            ]
        return []
    near = sorted(keys.intersection(policy.RULES_KEY_NEAR_MISSES))
    if near:
        return [
            f"{rel_path}: frontmatter has {', '.join(repr(k) for k in near)} but not "
            f"'{policy.RULES_FRONTMATTER_KEY}' — an unrecognised key is ignored silently, so "
            "this rule loads in every session instead of only for matching files"
        ]
    return [
        f"{rel_path}: frontmatter declares no '{policy.RULES_FRONTMATTER_KEY}' key, so this "
        "rule loads in every session rather than when a matching file is opened"
    ]


def check_rule_scope_matches(rel_path: str, lines: list[str], tracked: list[str]) -> list[str]:
    """Check 9 — every declared glob matches at least one tracked file.

    A pattern that matches nothing is a rule that never fires, which looks exactly like
    a rule that is working. Found immediately on the first six rules written to this
    contract: `lib/**/*.tsx` matched zero files, because the React components live under
    `artifacts/`, not `lib/`.
    """
    allowed = policy.DEAD_GLOB_EXCEPTIONS.get(rel_path, {})
    findings: list[str] = []
    for pattern in rule_globs(lines):
        if glob_matches(pattern, tracked):
            continue
        if pattern in allowed:
            if not allowed[pattern].strip():
                findings.append(
                    f"{rel_path}: dead-glob exception for {pattern!r} has an empty rationale"
                )
            else:
                logger.debug("%s: allowed forward-looking glob %r", rel_path, pattern)
            continue
        findings.append(
            f"{rel_path}: '{policy.RULES_FRONTMATTER_KEY}' pattern matches no tracked file, so "
            f"this rule never fires: {pattern}"
        )
    return findings


def excerpt(text: str, limit: int = 60) -> str:
    """A short, single-line excerpt of *text* for a finding message."""
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else f"{flat[:limit]}..."
