"""Markdown structure for ``tools/agents_docs``: sections, bullets, normative headings, citations."""

from __future__ import annotations

from collections.abc import Iterator

from tools.validate_skills import ORIGIN_LINK, is_checkable_path_token, is_path_shaped

from . import policy


def iter_sections(lines: list[str]) -> Iterator[tuple[str, list[str]]]:
    """Yield ``(heading, body)`` for each ``## `` section outside fenced blocks.

    Fence tracking matters: a ``## `` line inside a fenced example is illustration,
    not structure, and treating it as a heading would split a section in half.
    """
    heading: str | None = None
    body: list[str] = []
    in_fence = False
    for line in lines:
        if line.lstrip().startswith(policy.FENCE_PREFIX):
            in_fence = not in_fence
        elif not in_fence and line.startswith(policy.HEADING_PREFIX):
            if heading is not None:
                yield heading, body
            heading, body = line[len(policy.HEADING_PREFIX) :].strip(), []
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
        if policy.BULLET_RE.match(line):
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
    words = {word for word in policy.HEADING_WORD_SPLIT_RE.split(heading.casefold()) if word}
    return bool(words.intersection(policy.NORMATIVE_SECTION_KEYWORDS))


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
    — is resolved against its own directory too (see ``repo.resolution_bases``),
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
        or token.startswith(policy.RELATIVE_PREFIXES)
        or origin == ORIGIN_LINK
    )
