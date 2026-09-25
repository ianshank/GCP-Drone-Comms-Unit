#!/usr/bin/env python3
"""Lint the repository's agent instruction files.

The third mechanical sibling of ``tools/validate_workforce.py`` (``.claude/agents/``)
and ``tools/validate_skills.py`` (``.agents/skills/``). This one covers the files a
coding-agent harness loads as *trusted system context*: the ``AGENTS.md`` guides and
the path-scoped rules under ``.claude/rules/``.

Why it exists, in the order the checks matter:

* **Reference rot.** A guide citing a path that no longer exists sends an agent to a
  dead file. This is the class the skills linter already catches for skills.
* **Injection hygiene.** Instruction files are loaded without inspection, so a
  bidirectional-override or zero-width code point in one is a disclosed attack
  (the "rules-file backdoor"). Human review via ``CODEOWNERS`` is the real control;
  this is the cheap mechanical backstop.
* **Unrecorded rationale.** An instruction whose reason is lost cannot be safely
  deleted later, so it never is, and the file ratchets. Every rule carries a ``why:``.
* **Security rules that only look enforced.** A prose rule is not a control. Every
  security-relevant rule names the control that backs it, or says it is advisory.
* **A checker that goes quiet.** The two checks above are scoped by a heading match,
  so an unrecognised heading would switch them off while the run still printed a
  clean pass — a green line then reads as evidence of something never inspected.
  A file with no heading the rule checks can read is therefore itself a finding.

Design constraints, deliberately matching the two siblings: standalone, stdlib-only,
policy as module constants. Policy is **not** read from ``.claude/governance.yaml`` —
that file is loaded by ``scope_freeze.py``, which fails open on a config it cannot
validate, so a documentation typo must never be able to stop the Initiative-C freeze
from denying.

Usage::

    python tools/validate_agents_docs.py [--root PATH] [--verbose]

Exit status: 0 with a one-line summary when every instruction file is clean; 1 with
one finding per line on stdout otherwise. A non-zero exit from an operational problem
(not a git work tree) is reported distinctly from a policy finding.
"""

from __future__ import annotations

import argparse
import logging
import re
import subprocess
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path

if __package__ in (None, ""):
    # Executed directly (`python tools/validate_agents_docs.py`), so the repo root is
    # not on sys.path as a package parent. Add it and import the fully-qualified
    # module, rather than maintaining a second import path to a differently-named
    # top-level module — the same resolution scope_freeze.py and bind_guard.py use.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.validate_skills import (  # noqa: E402 (import follows the sys.path fix above)
    ORIGIN_LINK,
    is_checkable_path_token,
    is_path_shaped,
    iter_raw_path_tokens,
    repo_root,
)

logger = logging.getLogger("validate_agents_docs")


# --- Policy constants -------------------------------------------------------

#: Filename the harness treats as a repository guide.
GUIDE_FILENAME = "AGENTS.md"

#: The guide allowlist. Check 1 compares this against what git actually tracks, in
#: both directions: a guide committed outside this tuple is a finding (a new
#: instruction file is a deliberate decision, not a side effect), and an entry with
#: no file is a finding (a planned guide that was never written).
#:
#: Kept here rather than in `.claude/governance.yaml` — see the module docstring.
GUIDE_MANIFEST: tuple[str, ...] = (
    "AGENTS.md",
    "packages/meshsa/AGENTS.md",
    "packages/jetson_yolo_gcs/AGENTS.md",
    "ops/AGENTS.md",
    "hardware/AGENTS.md",
)

#: Path-scoped rules. Unlike guides these are *discovered*, not allowlisted: they all
#: live in one directory by construction, so there is no placement decision to police.
RULES_DIR = ".claude/rules"
RULES_GLOB = "*.md"

#: Section every guide must carry. Traps — facts that cost an agent a wasted turn or a
#: wrong result — are the one content type with a measured effect; repository
#: overviews are not, and are deliberately not required.
REQUIRED_GUIDE_SECTIONS: tuple[str, ...] = ("Traps",)

#: Words that mark a ``## `` heading as *normative* — the sections whose bullets
#: are instructions to obey, and so are subject to the rationale and control-tag
#: checks. Matched case-insensitively as whole words against the heading text, so
#: the three spellings already in the tree (``## Rules``, ``## Engineering Rules``,
#: ``## Framework Rules``, ``## Conventions (keep these invariant)``) all qualify
#: without enumerating headings.
#:
#: Matching on a keyword rather than the exact heading is what makes this survive
#: an ordinary rename; :func:`check_normative_section_present` is what stops an
#: *unrecognised* rename from silently switching the checks off. Both are needed:
#: the first check was written against the literal ``Rules`` and consequently ran
#: on two of the five guides, skipping the root guide — where the security-relevant
#: rules actually live — while reporting a clean pass.
NORMATIVE_SECTION_KEYWORDS: tuple[str, ...] = (
    "rules",
    "conventions",
    "invariants",
    "policy",
    "policies",
)

#: Characters separating words in a heading, for the keyword match above.
_HEADING_WORD_SPLIT_RE = re.compile(r"[^a-z0-9]+")

#: Marker introducing a rule's rationale, and the two markers that satisfy the
#: enforcement-disclosure requirement.
RATIONALE_MARKER = "why:"
CONTROL_MARKER = "control:"
ADVISORY_MARKER = "advisory"

#: Substrings that make a rule security-relevant, and so require CONTROL_MARKER or
#: ADVISORY_MARKER. Matched case-insensitively against the rule text.
#:
#: Plain substring matching, deliberately, and it is the inflections that make it the
#: right choice: ``auth`` has to reach ``authenticated`` and ``unauthenticated``, which
#: any word-boundary form would miss. The cost is that a keyword also matches inside an
#: identifier. Measured across the five guides as of this commit: five rules fire, four
#: on prose (``sockets``, ``credentials`` twice, ``secrets``) and one on an identifier
#: (``loopback`` inside ``LoopbackBus``, a test fake).
#:
#: That one is accepted rather than suppressed. Excluding backtick spans from the match
#: would remove it and would also stop a rule whose only security signal is an
#: identifier — say ``do not call `socket.bind()`` — from ever being checked, which is
#: the silent-miss mode :func:`check_normative_section_present` exists to prevent. A
#: false positive costs one ``— advisory`` clause, which is a true statement about that
#: rule; a false negative hides an unenforced security claim indefinitely.
SECURITY_KEYWORDS: tuple[str, ...] = (
    "bind",
    "listener",
    "socket",
    "token",
    "credential",
    "secret",
    "auth",
    "tls",
    "frozen",
    "c_gate_met",
    "scope_freeze",
    "unauthenticated",
    "loopback",
)

#: Code points that carry no legitimate meaning in an instruction file and that the
#: disclosed rules-file backdoor uses to hide payloads from a human reviewer:
#: bidirectional overrides/isolates and zero-width characters.
#:
#: A broader "ASCII-dominant" rule is deliberately *not* imposed: the authoring
#: contract itself mandates U+2014 in every `— why:` clause and U+00B7 in every
#: breadcrumb, so any density threshold would fire on the format it requires.
FORBIDDEN_CODE_POINTS: frozenset[str] = frozenset("‪‫‬‭‮⁦⁧⁨⁩​‌‍﻿")

#: The one frontmatter key Claude Code reads from a file under :data:`RULES_DIR`. It
#: scopes the rule to matching paths, so the rule loads when such a file is opened
#: rather than at session start.
#:
#: Checking for it matters because the failure is silent *and inverted*: a rule whose
#: frontmatter does not parse, or whose scoping key is misspelled, is not skipped — it
#: loads **unconditionally, in every session**, which is the opposite of the intent and
#: the outcome this change exists to avoid. Nothing reports that; the rule simply
#: becomes ambient context.
RULES_FRONTMATTER_KEY = "paths"

#: Plausible misspellings of :data:`RULES_FRONTMATTER_KEY`, reported by name because
#: the generic "no scoping key" message would otherwise send an author looking for a
#: missing line that is sitting right in front of them.
RULES_KEY_NEAR_MISSES: tuple[str, ...] = ("path", "globs", "glob", "appliesto", "applies_to")

#: Frontmatter fence.
FRONTMATTER_FENCE = "---"

#: Glob patterns a rule may declare that match nothing today, keyed by the rule's
#: repo-relative path, with the reason as the value. Forward-looking coverage is a
#: legitimate choice; it just has to be a stated one, because a pattern matching nothing
#: is otherwise indistinguishable from a typo — and both mean the rule never fires.
DEAD_GLOB_EXCEPTIONS: dict[str, dict[str, str]] = {}

#: Prefixes that make a token an explicit relative path, whatever it was written
#: inside. No English word begins with either, so accepting them adds no
#: false-positive surface.
RELATIVE_PREFIXES: tuple[str, ...] = ("../", "./")

#: Directory under a guide's own directory holding package sources. Used to build the
#: third resolution base, so `packages/jetson_yolo_gcs/AGENTS.md` citing
#: `detection/factory.py` resolves via `src/jetson_yolo_gcs/detection/factory.py`
#: instead of being reported missing.
PACKAGE_SOURCE_DIR = "src"

#: Citations a file may make to a path that deliberately does not exist, keyed by the
#: file's repo-relative path, then by token, with the rationale as the value. The
#: canonical case is a guide explaining why a given instruction file *cannot* be
#: created. An entry with an empty rationale is itself a finding.
CITATION_EXCEPTIONS: dict[str, dict[str, str]] = {}

#: Timeout for the single git invocation, matching tools/check_task_sync.py.
GIT_TIMEOUT_S = 60

_FENCE_PREFIX = "```"
_HEADING_PREFIX = "## "
#: A top-level list item: unordered (``- ``/``* ``) or ordered (``1. ``). Ordered items
#: are included because a normative section is free to number its rules, and
#: `packages/jetson_yolo_gcs/AGENTS.md` does — five rules that an unordered-only
#: pattern left unchecked while the run stayed green. No leading whitespace is allowed,
#: so an indented sub-item folds into its parent as a continuation rather than
#: being read as a separate rule.
_BULLET_RE = re.compile(r"^(?:[-*]|\d+\.)\s")


# --- Filesystem / git -------------------------------------------------------


def is_git_repo(root: Path) -> bool:
    """Whether *root* is inside a git work tree.

    Kept distinct from the enumeration below so running outside a checkout reports an
    operational error rather than an empty tree that looks like a manifest violation.
    """
    return (
        subprocess.run(  # noqa: S603 (fixed argv)
            ["git", "rev-parse", "--git-dir"],
            cwd=root,
            capture_output=True,
            timeout=GIT_TIMEOUT_S,
            check=False,
        ).returncode
        == 0
    )


def tracked_guides(root: Path) -> list[str]:
    """Repo-relative paths of every tracked file named :data:`GUIDE_FILENAME`.

    Enumerated with ``git ls-files`` rather than ``rglob`` so the result is exact
    (no ``node_modules``/``dist`` exclusion list to maintain) and so an untracked or
    ignored guide — which the harness would still load but review would never see —
    shows up as absent rather than silently passing.
    """
    result = subprocess.run(  # noqa: S603 (fixed argv)
        ["git", "ls-files", "--", f"*{GUIDE_FILENAME}"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_S,
        check=True,
    )
    return sorted(line for line in result.stdout.splitlines() if Path(line).name == GUIDE_FILENAME)


def tracked_files(root: Path) -> list[str]:
    """Every repo-relative path git tracks.

    Used to answer "does this rule's scope match anything", which needs the whole index
    rather than one filename pattern.
    """
    result = subprocess.run(  # noqa: S603 (fixed argv)
        ["git", "ls-files"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_S,
        check=True,
    )
    return result.stdout.splitlines()


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
    if not lines or lines[0].strip() != FRONTMATTER_FENCE:
        return []
    try:
        close = lines.index(FRONTMATTER_FENCE, 1)
    except ValueError:
        return []

    globs: list[str] = []
    in_paths = False
    for line in lines[1:close]:
        stripped = line.strip()
        if not line.startswith((" ", "\t", "-")) and ":" in line:
            key, _, value = line.partition(":")
            in_paths = key.strip().casefold() == RULES_FRONTMATTER_KEY
            if in_paths and value.strip():
                globs.extend(part.strip().strip("\"'") for part in value.split(",") if part.strip())
                in_paths = False
        elif in_paths and stripped.startswith("- "):
            globs.append(stripped[2:].strip().strip("\"'"))
    return [g for g in globs if g]


def discovered_rules(root: Path) -> list[str]:
    """Repo-relative paths of the path-scoped rule files, sorted."""
    rules_dir = root / RULES_DIR
    if not rules_dir.is_dir():
        return []
    return sorted(str(p.relative_to(root)) for p in rules_dir.glob(RULES_GLOB))


def resolution_bases(rel_path: str, root: Path) -> tuple[Path, ...]:
    """Directories a citation in *rel_path* may be relative to, in priority order.

    Three bases, which between them resolve every citation style in this repo:
    the file's own directory (``../AGENTS.md``), each package source root beneath it
    (``detection/factory.py`` under ``src/jetson_yolo_gcs/``), and the repo root
    (``packages/meshsa/src/...``).
    """
    own = (root / rel_path).parent
    bases: list[Path] = [own]
    source_root = own / PACKAGE_SOURCE_DIR
    if source_root.is_dir():
        bases.extend(sorted(child for child in source_root.iterdir() if child.is_dir()))
    bases.append(root)
    return tuple(bases)


def token_resolves(token: str, bases: Iterable[Path]) -> bool:
    """Whether *token* names an existing path under any of *bases*."""
    return any((base / token).exists() for base in bases)


# --- Markdown structure -----------------------------------------------------


def iter_sections(lines: list[str]) -> Iterator[tuple[str, list[str]]]:
    """Yield ``(heading, body)`` for each ``## `` section outside fenced blocks.

    Fence tracking matters: a ``## `` line inside a fenced example is illustration,
    not structure, and treating it as a heading would split a section in half.
    """
    heading: str | None = None
    body: list[str] = []
    in_fence = False
    for line in lines:
        if line.lstrip().startswith(_FENCE_PREFIX):
            in_fence = not in_fence
        elif not in_fence and line.startswith(_HEADING_PREFIX):
            if heading is not None:
                yield heading, body
            heading, body = line[len(_HEADING_PREFIX) :].strip(), []
            continue
        if heading is not None:
            body.append(line)
    if heading is not None:
        yield heading, body


def iter_bullets(body: list[str]) -> Iterator[str]:
    """Yield each bullet in *body* with its continuation lines folded in.

    A rule commonly wraps across lines; checking only the first would report a
    rationale as missing whenever the ``why:`` clause landed on the next line.
    """
    current: list[str] = []
    for line in body:
        if _BULLET_RE.match(line):
            if current:
                yield " ".join(current)
            current = [line.strip()]
        elif current and line.strip():
            current.append(line.strip())
        elif current:
            yield " ".join(current)
            current = []
    if current:
        yield " ".join(current)


def is_normative_heading(heading: str) -> bool:
    """Whether *heading* names a section of instructions to obey.

    Whole-word match so ``## Engineering Rules`` and ``## Conventions (keep these
    invariant)`` qualify while an incidental substring does not.
    """
    words = {word for word in _HEADING_WORD_SPLIT_RE.split(heading.casefold()) if word}
    return bool(words.intersection(NORMATIVE_SECTION_KEYWORDS))


def iter_normative_bullets(lines: list[str]) -> Iterator[str]:
    """Yield every bullet under every normative section of the file.

    All of them, not the first matching section's: the root guide carries its
    rules under one heading today but nothing stops a second from being added,
    and a checker that stopped at the first would go quiet on the rest.
    """
    for heading, body in iter_sections(lines):
        if is_normative_heading(heading):
            yield from iter_bullets(body)


def is_checkable_guide_token(token: str, origin: str) -> bool:
    """Whether a citation in a guide is worth resolving.

    Wider than :func:`is_checkable_path_token`, because a guide — unlike a skill
    — is resolved against its own directory too (see :func:`resolution_bases`),
    so guide-relative citations are meaningful here. Three accepted forms:

    * repo-root-relative, exactly as the skills linter treats them;
    * an explicit ``../`` or ``./`` prefix, which no prose word has; and
    * any path-shaped Markdown link target, since a link in a repository
      document is a path claim by construction — that is what admits
      ``[base-service](base-service)``.

    A bare backtick token stays rejected, which is what keeps prose such as
    ``SIGINT`` or the console-script name ``meshsa-base`` from being read as a
    missing file.
    """
    if not is_path_shaped(token):
        return False
    return (
        is_checkable_path_token(token)
        or token.startswith(RELATIVE_PREFIXES)
        or origin == ORIGIN_LINK
    )


# --- Checks -----------------------------------------------------------------


def check_manifest(root: Path) -> list[str]:
    """Check 1 — the tracked guide set and :data:`GUIDE_MANIFEST` agree both ways."""
    tracked = set(tracked_guides(root))
    declared = set(GUIDE_MANIFEST)
    findings = [
        f"{path}: tracked {GUIDE_FILENAME} is not in GUIDE_MANIFEST "
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
    """Check 2 — a guide carries every section in :data:`REQUIRED_GUIDE_SECTIONS`."""
    present = {heading for heading, _ in iter_sections(lines)}
    return [
        f"{rel_path}: missing required section '{_HEADING_PREFIX}{name}'"
        for name in REQUIRED_GUIDE_SECTIONS
        if name not in present
    ]


def check_cited_paths(rel_path: str, text: str, root: Path) -> list[str]:
    """Check 3 — every cited repo path resolves against one of its bases."""
    bases = resolution_bases(rel_path, root)
    allowed = CITATION_EXCEPTIONS.get(rel_path, {})
    findings: list[str] = []
    seen: set[str] = set()
    for token, origin in iter_raw_path_tokens(text, include_link_targets=True):
        if token in seen or not is_checkable_guide_token(token, origin):
            continue
        seen.add(token)
        if token_resolves(token, bases):
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
        if char in FORBIDDEN_CODE_POINTS
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
        f"{rel_path}: no normative section found — no '{_HEADING_PREFIX}' heading "
        f"contains any of {', '.join(NORMATIVE_SECTION_KEYWORDS)}, so the rule checks "
        "below would silently inspect nothing"
    ]


def check_rule_frontmatter(rel_path: str, lines: list[str]) -> list[str]:
    """Check 8 — a path-scoped rule actually declares its scope.

    Only the fences and the presence of the scoping key are checked, deliberately: the
    goal is to catch the inverted-failure case described on
    :data:`RULES_FRONTMATTER_KEY`, not to re-implement a YAML parser. A rule that meant
    to be ambient can say so by carrying no frontmatter at all — that is a decision,
    whereas a misspelled key looks like scoping and is not.
    """
    if not lines or lines[0].strip() != FRONTMATTER_FENCE:
        return [
            f"{rel_path}: no frontmatter block, so this rule loads in every session. "
            f"Add '{RULES_FRONTMATTER_KEY}:' to scope it, or state in-file that it is "
            "deliberately ambient"
        ]
    try:
        close = lines.index(FRONTMATTER_FENCE, 1)
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
    if RULES_FRONTMATTER_KEY in keys:
        return []
    near = sorted(keys.intersection(RULES_KEY_NEAR_MISSES))
    if near:
        return [
            f"{rel_path}: frontmatter has {', '.join(repr(k) for k in near)} but not "
            f"'{RULES_FRONTMATTER_KEY}' — an unrecognised key is ignored silently, so "
            "this rule loads in every session instead of only for matching files"
        ]
    return [
        f"{rel_path}: frontmatter declares no '{RULES_FRONTMATTER_KEY}' key, so this "
        "rule loads in every session rather than when a matching file is opened"
    ]


def check_rule_scope_matches(rel_path: str, lines: list[str], tracked: list[str]) -> list[str]:
    """Check 9 — every declared glob matches at least one tracked file.

    A pattern that matches nothing is a rule that never fires, which looks exactly like
    a rule that is working. Found immediately on the first six rules written to this
    contract: `lib/**/*.tsx` matched zero files, because the React components live under
    `artifacts/`, not `lib/`.
    """
    allowed = DEAD_GLOB_EXCEPTIONS.get(rel_path, {})
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
            f"{rel_path}: '{RULES_FRONTMATTER_KEY}' pattern matches no tracked file, so "
            f"this rule never fires: {pattern}"
        )
    return findings


def check_rule_rationale(rel_path: str, lines: list[str]) -> list[str]:
    """Check 6 — every rule records why it exists."""
    return [
        f"{rel_path}: rule has no '{RATIONALE_MARKER}' clause "
        f"(an unexplained rule cannot be safely deleted later): {_excerpt(bullet)}"
        for bullet in iter_normative_bullets(lines)
        if RATIONALE_MARKER not in bullet.casefold()
    ]


def check_security_control_tag(rel_path: str, lines: list[str]) -> list[str]:
    """Check 7 — a security-relevant rule names its control, or is marked advisory."""
    findings: list[str] = []
    for bullet in iter_normative_bullets(lines):
        folded = bullet.casefold()
        if not any(keyword in folded for keyword in SECURITY_KEYWORDS):
            continue
        if CONTROL_MARKER in folded or ADVISORY_MARKER in folded:
            continue
        findings.append(
            f"{rel_path}: security-relevant rule names no enforcing control "
            f"(add '{CONTROL_MARKER} <name>' or '{ADVISORY_MARKER}'): {_excerpt(bullet)}"
        )
    return findings


def _excerpt(text: str, limit: int = 60) -> str:
    """A short, single-line excerpt of *text* for a finding message."""
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else f"{flat[:limit]}..."


# --- Orchestration ----------------------------------------------------------


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
    for rel_path in sorted(set(GUIDE_MANIFEST) & set(tracked_guides(root))):
        findings.extend(validate_file(rel_path, root, require_sections=True))
    rules = discovered_rules(root)
    if rules:
        # Enumerated once and shared: the scope check needs the whole index, and
        # shelling out to git per rule file would be the same answer N times.
        tracked = tracked_files(root)
        for rel_path in rules:
            findings.extend(
                validate_file(rel_path, root, require_sections=False, is_rule=True, tracked=tracked)
            )
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
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
    if findings:
        for finding in findings:
            print(finding)
        print(f"FAIL: {len(findings)} finding(s) across the instruction files under {root}")
        return 1
    count = len(GUIDE_MANIFEST) + len(discovered_rules(root))
    print(f"OK: {count} instruction file(s) under {root} passed all checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
