#!/bin/bash
# SessionStart hook — provision the meshsa dev toolchain (ruff / mypy / pytest) so
# the quality gates run in Claude Code web/remote sessions. No-op outside the remote
# environment. Synchronous by design: the session waits for the install so the agent
# never races an unbuilt toolchain (the cause of spurious "import-not-found" errors).
set -euo pipefail

# Only provision in the remote (Claude Code on the web) environment.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

# Repository root: prefer the harness-provided project dir; fall back to this
# script's location so the hook also works when run directly for validation.
ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
cd "$ROOT"

# Core deps (pydantic / structlog) + dev toolchain. This mirrors
# .github/workflows/ci.yml exactly, so local gates match CI. Optional libraries
# (pymavlink, aiohttp, cv2, anthropic, ...) are covered by mypy's
# ignore_missing_imports override, so [dev] alone is enough for a green `mypy src`.
# pip is idempotent and the container caches the result, so re-runs are cheap.
# Best-effort pip upgrade: a Debian-managed pip cannot uninstall itself, so never
# let that abort the hook (the existing pip installs the package fine).
python -m pip install --quiet --upgrade pip 2>/dev/null || true
pip install --quiet -e "packages/meshsa[dev]"

# Gate invocation note: this environment ships `mypy`/`pytest` as isolated uv-tool
# installs that don't see the project deps. Run the gates from packages/meshsa via
# the project interpreter so they resolve correctly (ruff needs no resolution):
#   ruff check .  |  ruff format --check .  |  python -m mypy src  |  python -m pytest
echo "meshsa[dev] toolchain ready. Gates: ruff check . | python -m mypy src | python -m pytest"
