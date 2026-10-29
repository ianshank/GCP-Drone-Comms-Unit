#!/usr/bin/env python3
"""Lint the repository's agent instruction files.

The command-line entry point of the ``tools/agents_docs`` package (plan P2-6 split the
946-line single-file checker by check family; see that package's docstring for what the
nine checks are and why). CI, pre-commit, ``tools/Makefile`` and
``scripts/validate-pre-pr.sh`` all invoke this path, so it stays.

Usage::

    python tools/validate_agents_docs.py [--root PATH] [--verbose]

Exit status: 0 with a one-line summary when every instruction file is clean; 1 with
one finding per line on stdout otherwise. A non-zero exit from an operational problem
(not a git work tree) is reported distinctly from a policy finding.
"""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    # Executed directly (`python tools/validate_agents_docs.py`), so the repo root is
    # not on sys.path as a package parent. Add it and import the fully-qualified
    # package, rather than maintaining a second import path to a differently-named
    # top-level module — the same resolution scope_freeze.py and bind_guard.py use.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.agents_docs import main as main  # noqa: E402 (import follows the sys.path fix above)

if __name__ == "__main__":
    raise SystemExit(main())
