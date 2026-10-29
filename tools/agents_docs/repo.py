"""Git enumeration, glob matching and path resolution for ``tools/agents_docs``."""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

from tools._git import git_lines, git_ok

from . import policy

# --- Filesystem / git -------------------------------------------------------


def is_git_repo(root: Path) -> bool:
    """Whether *root* is inside a git work tree.

    Kept distinct from the enumeration below so running outside a checkout reports an
    operational error rather than an empty tree that looks like a manifest violation.
    """
    return git_ok(root, "rev-parse", "--git-dir")


def tracked_guides(root: Path) -> list[str]:
    """Repo-relative paths of every tracked file named :data:`policy.GUIDE_FILENAME`.

    Enumerated with ``git ls-files`` rather than ``rglob`` so the result is exact
    (no ``node_modules``/``dist`` exclusion list to maintain) and so an untracked or
    ignored guide — which the harness would still load but review would never see —
    shows up as absent rather than silently passing.
    """
    lines = git_lines(root, "ls-files", "--", f"*{policy.GUIDE_FILENAME}")
    return sorted(line for line in lines if Path(line).name == policy.GUIDE_FILENAME)


def tracked_files(root: Path) -> list[str]:
    """Every repo-relative path git tracks.

    Used to answer "does this rule's scope match anything", which needs the whole index
    rather than one filename pattern.
    """
    return git_lines(root, "ls-files")


# --- Globs ------------------------------------------------------------------


def _expand_braces(pattern: str) -> list[str]:
    """Expand one level of ``{a,b}`` alternation, recursively.

    Claude Code expands braces before matching, so ``src/**/*.{ts,tsx}`` is two
    patterns. Translating the braces into a regex alternation instead would be wrong
    for a nested case and would silently mis-report a live pattern as dead.
    """
    start = pattern.find("{")
    if start == -1:
        return [pattern]
    depth = 0
    for index in range(start, len(pattern)):
        if pattern[index] == "{":
            depth += 1
        elif pattern[index] == "}":
            depth -= 1
            if depth == 0:
                head, body, tail = pattern[:start], pattern[start + 1 : index], pattern[index + 1 :]
                expanded: list[str] = []
                for option in _split_top_level(body):
                    expanded.extend(_expand_braces(f"{head}{option}{tail}"))
                return expanded
    return [pattern]  # unbalanced brace: leave it alone rather than guess


def _split_top_level(body: str) -> list[str]:
    """Split ``a,b`` on commas that are not inside a nested brace group."""
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for char in body:
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        if char == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    parts.append("".join(current))
    return parts


def glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Compile one glob into a regex matched against a whole repo-relative path.

    Hand-rolled rather than via :func:`glob.translate`, which needs Python 3.13 while
    this repo supports 3.10–3.12. ``**`` crosses directory separators, a single ``*``
    and ``?`` do not.
    """
    out: list[str] = []
    index = 0
    while index < len(pattern):
        if pattern.startswith("**/", index):
            out.append("(?:.*/)?")
            index += 3
        elif pattern.startswith("**", index):
            out.append(".*")
            index += 2
        elif pattern[index] == "*":
            out.append("[^/]*")
            index += 1
        elif pattern[index] == "?":
            out.append("[^/]")
            index += 1
        else:
            out.append(re.escape(pattern[index]))
            index += 1
    return re.compile(f"^{''.join(out)}$")


def glob_matches(pattern: str, paths: Iterable[str]) -> bool:
    """Whether *pattern* (after brace expansion) matches any of *paths*.

    A trailing ``/**`` is also treated as matching the directory itself, matching the
    common intent of "this directory and everything under it".
    """
    for expanded in _expand_braces(pattern):
        candidates = [expanded]
        if expanded.endswith("/**"):
            candidates.append(expanded[: -len("/**")])
        for candidate in candidates:
            compiled = glob_to_regex(candidate)
            if any(compiled.match(path) for path in paths):
                return True
    return False


def rule_globs(lines: list[str]) -> list[str]:
    """The glob patterns declared under a rule's ``paths:`` key.

    Handles both documented spellings: a YAML list of strings, and a single
    comma-separated string.
    """
    if not lines or lines[0].strip() != policy.FRONTMATTER_FENCE:
        return []
    try:
        close = lines.index(policy.FRONTMATTER_FENCE, 1)
    except ValueError:
        return []

    globs: list[str] = []
    in_paths = False
    for line in lines[1:close]:
        stripped = line.strip()
        if not line.startswith((" ", "\t", "-")) and ":" in line:
            key, _, value = line.partition(":")
            in_paths = key.strip().casefold() == policy.RULES_FRONTMATTER_KEY
            if in_paths and value.strip():
                globs.extend(part.strip().strip("\"'") for part in value.split(",") if part.strip())
                in_paths = False
        elif in_paths and stripped.startswith("- "):
            globs.append(stripped[2:].strip().strip("\"'"))
    return [g for g in globs if g]


# --- Discovery and resolution -----------------------------------------------


def discovered_rules(root: Path) -> list[str]:
    """Repo-relative paths of the path-scoped rule files, sorted."""
    rules_dir = root / policy.RULES_DIR
    if not rules_dir.is_dir():
        return []
    return sorted(str(p.relative_to(root)) for p in rules_dir.glob(policy.RULES_GLOB))


def discovered_context_files(root: Path, tracked: list[str]) -> list[str]:
    """Tracked files matching :data:`policy.CONTEXT_SCAN_GLOBS`, sorted and de-duplicated.

    Drawn from the git index rather than the filesystem so an untracked instruction
    file — which a harness would still load but review would never see — is absent
    rather than quietly scanned and passed.
    """
    seen: set[str] = set()
    for pattern in policy.CONTEXT_SCAN_GLOBS:
        compiled = glob_to_regex(pattern)
        seen.update(path for path in tracked if compiled.match(path))
    return sorted(seen)


def resolution_bases(rel_path: str, root: Path) -> tuple[Path, ...]:
    """Directories a citation in *rel_path* may be relative to, in priority order.

    Three bases, which between them resolve every citation style in this repo:
    the file's own directory (``../AGENTS.md``), each package source root beneath it
    (``detection/factory.py`` under ``src/jetson_yolo_gcs/``), and the repo root
    (``packages/meshsa/src/...``).
    """
    own = (root / rel_path).parent
    bases: list[Path] = [own]
    source_root = own / policy.PACKAGE_SOURCE_DIR
    if source_root.is_dir():
        bases.extend(sorted(child for child in source_root.iterdir() if child.is_dir()))
    bases.append(root)
    return tuple(bases)


def token_resolves(token: str, bases: Iterable[Path]) -> bool:
    """Whether *token* names an existing path under any of *bases*."""
    return any((base / token).exists() for base in bases)
