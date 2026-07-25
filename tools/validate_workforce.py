#!/usr/bin/env python3
"""Lint the Claude Code subagent roster under ``.claude/agents/``.

Standalone and stdlib-only. Roster frontmatter is the simple ``key: value``
subset between the first two ``---`` lines; a small dedicated parser below
handles exactly that instead of pulling in a YAML dependency.

Usage::

    python tools/validate_workforce.py [--roster-dir PATH] [--verbose]

Exit status: 0 with a one-line summary when the roster is clean; 1 with one
finding per line on stdout otherwise.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger("validate_workforce")

# --- Policy constants -------------------------------------------------------
# Ratified in the accepted spec: openspec/changes/gcp-drone-m2-agent-hardening.
# Maximum total lines per roster file, frontmatter included.
MAX_LINES = 60
# Frontmatter keys every roster file must define (non-empty).
REQUIRED_KEYS = ("name", "description", "tools")
# Every roster body must contain a line starting with this marker, stating the
# agent's link to existing infra (or "none — new mandate").
RELATIONSHIP_MARKER = "Relationship:"
# Prose punctuation stripped from tokens when checking Relationship paths.
# Leading dots are preserved so dotted repo paths (".github/...") survive.
_TOKEN_STRIP = "`\"'(),;"


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
    nesting, lists, or multi-line values) — the roster does not use more.
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


def relationship_path_findings(value: str, root: Path) -> list[str]:
    """Repo-path tokens (containing ``/``) in *value* that do not exist."""
    missing: list[str] = []
    for raw in value.split():
        token = raw.strip(_TOKEN_STRIP).rstrip(".")
        if "/" in token and not (root / token).exists():
            missing.append(token)
    return missing


def validate_file(path: Path, root: Path) -> tuple[list[str], str | None]:
    """Validate one roster file; return (findings, declared agent name)."""
    logger.debug("validating %s", path)
    lines = path.read_text(encoding="utf-8").splitlines()

    findings: list[str] = []
    if len(lines) > MAX_LINES:
        findings.append(f"{len(lines)} lines exceeds the {MAX_LINES}-line limit")

    name: str | None = None
    frontmatter = parse_frontmatter(lines)
    if frontmatter is None:
        findings.append("frontmatter missing or malformed (key: value between --- fences)")
    else:
        missing = [key for key in REQUIRED_KEYS if not frontmatter.get(key)]
        if missing:
            findings.append(f"frontmatter missing required key(s): {', '.join(missing)}")
        name = frontmatter.get("name")
        if name and name != path.stem:
            findings.append(f"frontmatter name {name!r} != filename stem {path.stem!r}")

    body = body_lines(lines)
    relationship = [line for line in body if line.startswith(RELATIONSHIP_MARKER)]
    if not relationship:
        findings.append(f"body has no line starting with {RELATIONSHIP_MARKER!r}")
    for line in relationship:
        value = line[len(RELATIONSHIP_MARKER) :].strip()
        for token in relationship_path_findings(value, root):
            findings.append(f"Relationship path does not exist in repo: {token}")
    return findings, name


def validate_roster(roster_dir: Path, root: Path) -> list[str]:
    """Validate every ``*.md`` in *roster_dir*; return all findings."""
    if not roster_dir.is_dir():
        return [f"{roster_dir}: roster directory does not exist"]
    files = sorted(roster_dir.glob("*.md"))
    if not files:
        return [f"{roster_dir}: contains no .md roster files"]

    findings: list[str] = []
    seen: dict[str, str] = {}
    for path in files:
        file_findings, name = validate_file(path, root)
        findings.extend(f"{path.name}: {finding}" for finding in file_findings)
        if name is None:
            continue
        if name in seen:
            findings.append(f"{path.name}: duplicate agent name {name!r} (also in {seen[name]})")
        else:
            seen[name] = path.name
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--roster-dir",
        type=Path,
        default=None,
        help="Roster directory (default: .claude/agents under the repo root).",
    )
    parser.add_argument("--verbose", action="store_true", help="Emit a debug trace to stderr.")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING, stream=sys.stderr)

    root = repo_root()
    roster_dir = args.roster_dir if args.roster_dir is not None else root / ".claude" / "agents"
    logger.debug("repo root: %s; roster dir: %s", root, roster_dir)

    findings = validate_roster(roster_dir, root)
    if findings:
        for finding in findings:
            print(finding)
        print(f"FAIL: {len(findings)} finding(s) in {roster_dir}")
        return 1
    count = len(list(roster_dir.glob("*.md")))
    print(f"OK: {count} roster file(s) in {roster_dir} passed all checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
