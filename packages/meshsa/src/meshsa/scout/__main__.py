"""``python -m meshsa.scout`` entry point."""

from __future__ import annotations

import sys

from .cli import run

if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(run(sys.argv[1:]))
