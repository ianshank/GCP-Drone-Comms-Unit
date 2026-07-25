"""Pytest wiring for the governance hook tests.

Puts the repository root on ``sys.path`` so ``tools.claude_hooks.*`` imports
resolve regardless of how pytest was invoked (``python -m pytest`` from the
repo root already provides this; a bare ``pytest`` from elsewhere does not).
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
