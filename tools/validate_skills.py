#!/usr/bin/env python3
"""Lint the Claude Code skill playbooks under ``.agents/skills/``.

The mechanical twin of ``tools/validate_workforce.py`` (which covers
``.claude/agents/``): until this script existed, nothing mechanically checked
a ``SKILL.md``'s frontmatter, its `name`-vs-directory agreement, or whether the
repo-relative paths it cites still exist — the exact class of drift this
branch spent a full audit pass fixing by hand elsewhere (CHANGELOG, NEXTSTEPS,
session-start.sh, ...). This closes that gap for skills specifically.

Standalone and stdlib-only, same design as ``validate_workforce.py``: the
frontmatter is the simple ``key: value`` subset between the first two ``---``
lines, parsed by a small dedicated parser rather than pulling in a YAML
dependency.

Usage::

    python tools/validate_skills.py [--skills-dir PATH] [--verbose]

Exit status: 0 with a one-line summary when every skill is clean; 1 with one
finding per line on stdout otherwise.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from pathlib import Path

logger = logging.getLogger("validate_skills")

# --- Policy constants -------------------------------------------------------
# Frontmatter keys every SKILL.md must define (non-empty). Matches the
# convention all 12 skills already follow (`name`, `description`,
# `argument-hint`); a skill missing one of these breaks Claude Code's skill
# discovery, not just documentation quality.
REQUIRED_KEYS = ("name", "description", "argument-hint")
# The trigger-phrase convention every skill's description currently opens
# with — it's what makes a skill auto-invocable from context rather than only
# by explicit name; drifting from it silently degrades discovery.
DESCRIPTION_PREFIX = "Use when:"
# A SKILL.md with no `##` section at all is a stub, not a playbook.
MIN_BODY_HEADINGS = 1

# Prose punctuation stripped from tokens when checking cited paths. Mirrors
# validate_workforce.py's _TOKEN_STRIP, plus ':' for a trailing colon before a
# code block.
_TOKEN_STRIP = "`\"'(),;:"

#: Repo-root-relative prefixes a backtick-quoted, slash-containing token must
#: start with to be treated as a checkable path reference. Skill bodies also
#: use bare module-relative shorthand (`mavlink/pose.py`, `command/audit.py`)
#: that is not repo-root-relative — those are intentionally left unchecked
#: rather than mis-flagged, since only the maintainer's actual package layout
#: (context this script does not have) could resolve them correctly.
CHECKABLE_PATH_PREFIXES: tuple[str, ...] = (
    "packages/",
    "docs/",
    "openspec/",
    "flightctl/",
    "tools/",
    "ops/",
    ".claude/",
    ".agents/",
    ".github/",
    "hardware/",
    "deliverables/",
    "archive/",
)
#: Bare (slash-free) root filenames worth checking when cited directly.
CHECKABLE_ROOT_FILES: frozenset[str] = frozenset(
    {
        "AGENTS.md",
        "CLAUDE.md",
        "README.md",
        "CHANGELOG.md",
        "CONTRIBUTING.md",
        "NEXTSTEPS.md",
        "SECURITY.md",
        "Makefile",
    }
)
#: Characters that mark a token as a template/glob placeholder, not a
#: concrete path (`docs/specs/<slug>.md`, `tests/test_command_*.py`,
#: `.../{pose,timesync}.py`) — deliberately unchecked rather than resolved,
#: since expanding them correctly would need real glob/brace semantics for a
#: gain that's out of proportion to the risk they're covering for.
_PLACEHOLDER_CHARS = "*<>{}"

_BACKTICK_SPAN_RE = re.compile(r"`([^`]+)`")


def repo_root() -> Path:
    """Repo root from ``$CLAUDE_PROJECT_DIR``, else this script's parent dir."""
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return Path(env).resolve()
    return Path(__file__).resolve().parent.parent


def parse_frontmatter(lines: list[str]) -> dict[str, str] | None:
    """Parse ``key: value`` frontmatter between the first two ``---`` lines.

    Returns ``None`` when the file has no well-formed frontmatter block.
    Values may be wrapped in single or double quotes; nothing fancier (no
    nesting, lists, or multi-line values) — the skill roster does not use
    more than that.
    """
    if not lines or lines[0].strip() != "---":
        return None
    data: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return data
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, sep, value = line.partition(":")
        if not sep or not key.strip() or " " in key.strip():
            logger.debug("malformed frontmatter line: %r", line)
            return None
        data[key.strip()] = value.strip().strip("\"'")
    logger.debug("frontmatter closing fence never found")
    return None


def body_lines(lines: list[str]) -> list[str]:
    """Lines after the closing frontmatter fence (empty if no valid fences)."""
    fences = 0
    for index, line in enumerate(lines):
        if line.strip() == "---":
            fences += 1
            if fences == 2:
                return lines[index + 1 :]
    return []


def _is_checkable_path_token(token: str) -> bool:
    """Whether *token* looks like a concrete, repo-root-relative path."""
    if not token or any(char in token for char in _PLACEHOLDER_CHARS):
        return False
    if "/" in token:
        return token.startswith(CHECKABLE_PATH_PREFIXES)
    return token in CHECKABLE_ROOT_FILES


def cited_path_findings(body: list[str], root: Path) -> list[str]:
    """Repo-relative paths cited in backtick spans across *body* that are missing."""
    missing: list[str] = []
    seen: set[str] = set()
    for line in body:
        for span in _BACKTICK_SPAN_RE.findall(line):
            for raw in span.split():
                token = raw.strip(_TOKEN_STRIP).rstrip(".")
                if not _is_checkable_path_token(token) or token in seen:
                    continue
                seen.add(token)
                if not (root / token).exists():
                    missing.append(token)
    return missing


def validate_file(path: Path, root: Path) -> tuple[list[str], str | None]:
    """Validate one SKILL.md; return (findings, declared skill name)."""
    logger.debug("validating %s", path)
    lines = path.read_text(encoding="utf-8").splitlines()
    dir_name = path.parent.name

    findings: list[str] = []
    name: str | None = None
    frontmatter = parse_frontmatter(lines)
    if frontmatter is None:
        findings.append("frontmatter missing or malformed (key: value between --- fences)")
    else:
        missing = [key for key in REQUIRED_KEYS if not frontmatter.get(key)]
        if missing:
            findings.append(f"frontmatter missing required key(s): {', '.join(missing)}")
        name = frontmatter.get("name")
        if name and name != dir_name:
            findings.append(f"frontmatter name {name!r} != skill directory {dir_name!r}")
        description = frontmatter.get("description")
        if description and not description.startswith(DESCRIPTION_PREFIX):
            findings.append(
                f"description does not start with {DESCRIPTION_PREFIX!r} "
                "(breaks the auto-invocation trigger-phrase convention)"
            )

    body = body_lines(lines)
    if sum(1 for line in body if line.startswith("## ")) < MIN_BODY_HEADINGS:
        findings.append(f"body has fewer than {MIN_BODY_HEADINGS} '## ' section heading(s)")
    for token in cited_path_findings(body, root):
        findings.append(f"cited path does not exist in repo: {token}")
    return findings, name


def validate_skills(skills_dir: Path, root: Path) -> list[str]:
    """Validate every ``*/SKILL.md`` under *skills_dir*; return all findings."""
    if not skills_dir.is_dir():
        return [f"{skills_dir}: skills directory does not exist"]
    files = sorted(skills_dir.glob("*/SKILL.md"))
    if not files:
        return [f"{skills_dir}: contains no */SKILL.md files"]

    findings: list[str] = []
    seen: dict[str, str] = {}
    for path in files:
        rel = path.relative_to(skills_dir)
        file_findings, name = validate_file(path, root)
        findings.extend(f"{rel}: {finding}" for finding in file_findings)
        if name is None:
            continue
        if name in seen:
            findings.append(f"{rel}: duplicate skill name {name!r} (also in {seen[name]})")
        else:
            seen[name] = str(rel)
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--skills-dir",
        type=Path,
        default=None,
        help="Skills directory (default: .agents/skills under the repo root).",
    )
    parser.add_argument("--verbose", action="store_true", help="Emit a debug trace to stderr.")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING, stream=sys.stderr)

    root = repo_root()
    skills_dir = args.skills_dir if args.skills_dir is not None else root / ".agents" / "skills"
    logger.debug("repo root: %s; skills dir: %s", root, skills_dir)

    findings = validate_skills(skills_dir, root)
    if findings:
        for finding in findings:
            print(finding)
        print(f"FAIL: {len(findings)} finding(s) in {skills_dir}")
        return 1
    count = len(list(skills_dir.glob("*/SKILL.md")))
    print(f"OK: {count} skill file(s) in {skills_dir} passed all checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
