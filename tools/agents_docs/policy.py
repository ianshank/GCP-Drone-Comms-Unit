"""Policy constants for the instruction-file linter (``tools/agents_docs``).

Policy is **not** read from ``.claude/governance.yaml`` — that file is loaded by
``scope_freeze.py``, which fails open on a config it cannot validate, so a documentation
typo must never be able to stop the Initiative-C freeze from denying. The checks read
these names through this module at call time (``policy.GUIDE_MANIFEST``), so a test can
narrow a table with ``monkeypatch.setattr(policy, ...)``.
"""

from __future__ import annotations

import re

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

#: Every other file some harness loads as trusted system context. These get the
#: control-character check only — they are not guides, so a ``## Traps`` section or a
#: ``— why:`` clause would be the wrong demand — but the injection surface is identical
#: and was previously unscanned by anything: neither ``validate_skills.py`` nor
#: ``validate_workforce.py`` looks for hidden code points, so a Tags-block payload in a
#: subagent definition or in ``CLAUDE.md`` passed the whole gate.
#:
#: ``CLAUDE.md`` matters most here: it is Claude Code's entry point and the file whose
#: ``@AGENTS.md`` import makes every guide load at all.
CONTEXT_SCAN_GLOBS: tuple[str, ...] = (
    "CLAUDE.md",
    "**/CLAUDE.md",
    ".github/copilot-instructions.md",
    ".agents/skills/*/SKILL.md",
    ".claude/agents/*.md",
    ".github/agents/*.md",
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
#: an ordinary rename; ``check_normative_section_present`` is what stops an
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
HEADING_WORD_SPLIT_RE = re.compile(r"[^a-z0-9]+")

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
#: the silent-miss mode ``check_normative_section_present`` exists to prevent. A
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
#: disclosed rules-file backdoor uses to hide payloads from a human reviewer.
#:
#: Built as ranges rather than a literal string so the set is readable in source and so
#: the Tags block can be included at all — it is 128 code points, and every one of them
#: renders as nothing while round-tripping ASCII exactly. Tags are the canonical
#: invisible-ASCII smuggling encoding and the most published one, so a deny-list that
#: omitted them would name the attack in its own docstring and then miss its primary
#: form.
#:
#: A broader "ASCII-dominant" or density rule is still deliberately *not* imposed: the
#: authoring contract itself mandates U+2014 in every `— why:` clause and U+00B7 in
#: every breadcrumb, so any threshold would fire on the format it requires. That
#: argument does not extend to an explicit list of non-rendering code points, which is
#: why this set is broad where a density rule cannot be.
FORBIDDEN_CODE_POINT_RANGES: tuple[tuple[int, int, str], ...] = (
    (0x00AD, 0x00AD, "soft hyphen"),
    (0x180E, 0x180E, "Mongolian vowel separator"),
    (0x200B, 0x200F, "zero-width space/joiners and LRM/RLM"),
    (0x202A, 0x202E, "bidirectional embeddings and overrides"),
    (0x2060, 0x2064, "word joiner and invisible operators"),
    (0x2066, 0x2069, "bidirectional isolates"),
    (0xFE00, 0xFE0F, "variation selectors"),
    (0xFEFF, 0xFEFF, "zero-width no-break space / BOM"),
    (0xE0000, 0xE007F, "Unicode Tags block — invisible ASCII"),
    (0xE0100, 0xE01EF, "variation selectors supplement"),
)

FORBIDDEN_CODE_POINTS: frozenset[str] = frozenset(
    chr(cp) for low, high, _ in FORBIDDEN_CODE_POINT_RANGES for cp in range(low, high + 1)
)

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

#: Rules that deliberately carry no ``paths:`` scope and so load in every session,
#: keyed by repo-relative path with the reason as the value. An ambient rule is a
#: legitimate choice — it is how a rule becomes always-on context, the same priority as
#: ``.claude/CLAUDE.md`` — but it widens the always-on surface this change exists to keep
#: narrow, so it has to be a stated decision rather than an omission. An entry with an
#: empty rationale is itself a finding, as with the other two exception tables.
AMBIENT_RULE_EXCEPTIONS: dict[str, str] = {}

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

#: Documents swept for dead path citations as an ADVISORY (plan P1-3): each finding is
#: printed as a warning and never changes the exit code. These are not instruction files,
#: so their checks are not the trusted-context obligation above — but a dead path in the
#: README or the stable plan is the same reference rot, and it was invisible until now.
#: Gating waits for the docs/ reorganization (plan H1 / P3-3); gating today would fail on
#: historical review documents that cite paths which no longer exist by design.
#: Patterns match one directory level: ``docs/*.md`` does not reach ``docs/reviews/``.
DOCS_ADVISORY_GLOBS: tuple[str, ...] = (
    "README.md",
    "docs/*.md",
    "docs/specs/*.md",
    "docs/architecture/*.md",
    "docs/adr/*.md",
)

FENCE_PREFIX = "```"
HEADING_PREFIX = "## "
#: A top-level list item: unordered (``- ``/``* ``) or ordered (``1. ``). Ordered items
#: are included because a normative section is free to number its rules, and
#: `packages/jetson_yolo_gcs/AGENTS.md` does — five rules that an unordered-only
#: pattern left unchecked while the run stayed green. No leading whitespace is allowed,
#: so an indented sub-item folds into its parent as a continuation rather than
#: being read as a separate rule.
BULLET_RE = re.compile(r"^(?:[-*]|\d+\.)\s")
