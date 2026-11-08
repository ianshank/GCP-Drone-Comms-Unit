"""Lint the repository's agent instruction files.

Orchestration and the command line of ``tools/agents_docs``: which files get which checks,
the advisory docs sweep, and the exit-status contract.

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


def advisory_docs_citations(root: Path, tracked: list[str]) -> list[str]:
    """Advisory sweep — dead path citations in README.md and the stable docs/ tree.

    Reuses :func:`check_cited_paths` unchanged, so a citation is judged exactly as it
    would be in a guide; only the consequence differs (a warning, never a failure).
    """
    warnings: list[str] = []
    for rel_path in sorted(
        path
        for path in tracked
        if any(matches_single_level_glob(path, pattern) for pattern in policy.DOCS_ADVISORY_GLOBS)
    ):
        path = root / rel_path
        if not path.is_file():
            continue
        warnings.extend(check_cited_paths(rel_path, path.read_text(encoding="utf-8"), root))
    return warnings


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

    findings = validate_instruction_files(root)
    # Advisory, printed before the verdict so it never reads as part of it. GitHub's
    # `::warning` prefix turns each line into a run annotation and is harmless elsewhere.
    for warning in advisory_docs_citations(root, tracked_files(root)):
        # No comma inside title=: the runner splits the property list on commas.
        print(f"::warning title=docs citation advisory (plan P1-3)::{warning}")
    if findings:
        for finding in findings:
            print(finding)
        print(f"FAIL: {len(findings)} finding(s) across the instruction files under {root}")
        return 1
    instruction_count = len(policy.GUIDE_MANIFEST) + len(discovered_rules(root))
    context_count = len(discovered_context_files(root, tracked_files(root)))
    print(
        f"OK: {instruction_count} instruction file(s) under {root} passed all checks "
        f"({context_count} further context file(s) scanned for hidden code points)"
    )
    return 0
