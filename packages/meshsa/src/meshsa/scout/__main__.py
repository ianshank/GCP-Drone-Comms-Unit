"""``python -m meshsa.scout`` entry point."""

from __future__ import annotations  # pragma: no cover - module entry point

import sys  # pragma: no cover - module entry point

from .cli import run  # pragma: no cover - module entry point

if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(run(sys.argv[1:]))
