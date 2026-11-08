"""Lint the repository's agent instruction files.

Orchestration and the command line of ``tools/agents_docs``: which files get which checks,
the docs citation sweep, and the exit-status contract.

Usage::

    python tools/validate_agents_docs.py [--root PATH] [--verbose]

Exit status: 0 with a one-line summary when every instruction file is clean; 1 with
one finding per line on stdout otherwise. A non-zero exit from an operational problem
(not a git work tree) is reported distinctly from a policy finding.
"""

from __future__ import annotations

import argparse
import fnmatch
import logging
import sys
from pathlib import Path

from tools.validate_skills import repo_root

from . import policy
from .checks import (
    check_cited_paths,
    check_control_characters,
    check_manifest,
    check_normative_section_present,
    check_required_sections,
    check_rule_frontmatter,
    check_rule_rationale,
    check_rule_scope_matches,
    check_security_control_tag,
)
from .repo import (
    discovered_context_files,
    discovered_rules,
    is_git_repo,
    tracked_files,
    tracked_guides,
)

logger = logging.getLogger("validate_agents_docs")


def validate_file(
    rel_path: str,
    root: Path,
    *,
    require_sections: bool,
    is_rule: bool = False,
    tracked: list[str] | None = None,
) -> list[str]:
    """Run every per-file check against one instruction file."""
    logger.debug(
        "validating %s (require_sections=%s, is_rule=%s)", rel_path, require_sections, is_rule
    )
    path = root / rel_path
    if not path.is_file():
        return [f"{rel_path}: file does not exist"]
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    findings: list[str] = []
    if require_sections:
        findings.extend(check_required_sections(rel_path, lines))
    if is_rule:
        findings.extend(check_rule_frontmatter(rel_path, lines))
        findings.extend(
            check_rule_scope_matches(
                rel_path, lines, tracked if tracked is not None else tracked_files(root)
            )
        )
    findings.extend(check_cited_paths(rel_path, text, root))
    findings.extend(check_control_characters(rel_path, text))
    # Runs for rules files too, not just guides: a rules file with no normative
    # heading is one whose every rule is unchecked, which is the case the check
    # exists for.
    findings.extend(check_normative_section_present(rel_path, lines))
    findings.extend(check_rule_rationale(rel_path, lines))
    findings.extend(check_security_control_tag(rel_path, lines))
    return findings


def validate_instruction_files(root: Path) -> list[str]:
    """Validate every guide and path-scoped rule; return all findings."""
    findings = check_manifest(root)
    for rel_path in sorted(set(policy.GUIDE_MANIFEST) & set(tracked_guides(root))):
        findings.extend(validate_file(rel_path, root, require_sections=True))
    tracked_all = tracked_files(root)
    for rel_path in discovered_context_files(root, tracked_all):
        path = root / rel_path
        if not path.is_file():
            continue
        # Control characters only: these are not guides, so the section and rationale
        # checks would be the wrong obligation. The injection surface is the same.
        findings.extend(check_control_characters(rel_path, path.read_text(encoding="utf-8")))

    rules = discovered_rules(root)
    if rules:
        # Enumerated once and shared: the scope check needs the whole index, and
        # shelling out to git per rule file would be the same answer N times.
        tracked = tracked_all
        for rel_path in rules:
            findings.extend(
                validate_file(rel_path, root, require_sections=False, is_rule=True, tracked=tracked)
            )
    return findings


def matches_single_level_glob(rel_path: str, pattern: str) -> bool:
    """``fnmatch`` where ``*`` stops at ``/``: ``docs/*.md`` matches ``docs/a.md`` only."""
    return rel_path.count("/") == pattern.count("/") and fnmatch.fnmatch(rel_path, pattern)


def docs_citation_targets(tracked: list[str]) -> list[str]:
    """The tracked files :data:`policy.DOCS_CITATION_GLOBS` selects, sorted."""
    return sorted(
        path
        for path in tracked
        if any(matches_single_level_glob(path, pattern) for pattern in policy.DOCS_CITATION_GLOBS)
    )


def check_docs_citations(root: Path, tracked: list[str]) -> list[str]:
    """Dead path citations in README.md and the stable docs/ tree — findings, not warnings.

    Reuses :func:`check_cited_paths` unchanged, so a citation is judged exactly as it
    would be in a guide. Advisory from plan P1-3 until the historical records moved out of
    reach (P3-3); gating since.
    """
    findings: list[str] = []
    for rel_path in docs_citation_targets(tracked):
        path = root / rel_path
        if not path.is_file():
            continue
        findings.extend(check_cited_paths(rel_path, path.read_text(encoding="utf-8"), root))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Repository root (default: $CLAUDE_PROJECT_DIR, else this script's parent).",
    )
    parser.add_argument("--verbose", action="store_true", help="Emit a debug trace to stderr.")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING, stream=sys.stderr)

    root = args.root.resolve() if args.root is not None else repo_root()
    logger.debug("repo root: %s", root)

    if not is_git_repo(root):
        print(f"ERROR: {root} is not a git work tree; cannot enumerate instruction files")
        return 2

    tracked = tracked_files(root)
    findings = validate_instruction_files(root) + check_docs_citations(root, tracked)
    if findings:
        for finding in findings:
            print(finding)
        print(f"FAIL: {len(findings)} finding(s) across the instruction files under {root}")
        return 1
    instruction_count = len(policy.GUIDE_MANIFEST) + len(discovered_rules(root))
    context_count = len(discovered_context_files(root, tracked))
    docs_count = len(docs_citation_targets(tracked))
    print(
        f"OK: {instruction_count} instruction file(s) under {root} passed all checks "
        f"({context_count} further context file(s) scanned for hidden code points, "
        f"{docs_count} doc(s) checked for dead citations)"
    )
    return 0
