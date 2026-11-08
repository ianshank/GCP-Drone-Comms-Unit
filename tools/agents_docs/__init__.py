"""Lint the repository's agent instruction files (the ``tools/validate_agents_docs.py`` CLI).

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
policy as module constants (``policy.py``). The package is split by check family (plan
P2-6): ``policy`` (the tables), ``repo`` (git, globs, resolution), ``markdown``
(sections, bullets, citations), ``checks`` (the nine checks) and ``cli`` (orchestration
and the entry point). Everything a caller or test needs is re-exported here.
"""

from __future__ import annotations

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
    excerpt,
)
from .cli import (
    advisory_docs_citations,
    main,
    matches_single_level_glob,
    validate_file,
    validate_instruction_files,
)
from .markdown import (
    is_checkable_guide_token,
    is_normative_heading,
    iter_bullets,
    iter_normative_bullets,
    iter_sections,
)
from .repo import (
    discovered_context_files,
    discovered_rules,
    glob_matches,
    glob_to_regex,
    is_git_repo,
    resolution_bases,
    rule_globs,
    token_resolves,
    tracked_files,
    tracked_guides,
)

__all__ = [
    "advisory_docs_citations",
    "check_cited_paths",
    "check_control_characters",
    "check_manifest",
    "check_normative_section_present",
    "check_required_sections",
    "check_rule_frontmatter",
    "check_rule_rationale",
    "check_rule_scope_matches",
    "check_security_control_tag",
    "discovered_context_files",
    "discovered_rules",
    "excerpt",
    "glob_matches",
    "glob_to_regex",
    "is_checkable_guide_token",
    "is_git_repo",
    "is_normative_heading",
    "iter_bullets",
    "iter_normative_bullets",
    "iter_sections",
    "main",
    "matches_single_level_glob",
    "resolution_bases",
    "rule_globs",
    "token_resolves",
    "tracked_files",
    "tracked_guides",
    "validate_file",
    "validate_instruction_files",
]
