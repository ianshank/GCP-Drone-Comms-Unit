# Claude Code Guide

The canonical guide is imported below, so Claude Code loads it mechanically rather
than relying on this file's prose. A Markdown link would not: with any `CLAUDE.md`
at or above the working directory, Claude Code's default instruction mode reads
`CLAUDE.md` files only, so before this import no `AGENTS.md` in the repository was
loaded at all.

@AGENTS.md

Also read the nearest scoped `AGENTS.md` in the folder you are editing. This file
exists only for Claude Code discovery; keep project rules in AGENTS.md.

Claude-specific notes:

- On Windows, use PowerShell syntax and quote paths containing spaces.
- Prefer `rg` when available; otherwise use PowerShell search commands or editor
  search tools.
- Do not run destructive git commands or rewrite user changes without explicit
  approval.
- Before broad framework edits, check [.agents/skills](.agents/skills) for a
  narrower playbook.
- For final verification, run package commands from `packages/meshsa` so mypy
  reads the package-local `pyproject.toml`.
- Delegate per the subagent roster in [.claude/agents](.claude/agents) (see the
  AGENTS.md "Subagent roster" section); the scope-freeze hook and
  `.claude/governance.yaml` gate the Initiative-C command path.
