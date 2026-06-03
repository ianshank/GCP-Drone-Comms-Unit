# Claude Code Guide

Read [AGENTS.md](AGENTS.md) first, then the nearest scoped `AGENTS.md` in the
folder you are editing. This file exists only for Claude Code discovery; keep
project rules in AGENTS.md.

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