#!/usr/bin/env bash
# =============================================================================
# setup_fts.sh — create the FreeTAKServer Python 3.11 venv on the SSD and install
# FreeTAKServer with the dependency pins VERIFIED to boot on this box
# (Jetson Orin Nano, JetPack 6.2, aarch64). Run as your normal user (uses uv).
#
# Why the extra pins (discovered by actually booting FTS 2.x here):
#   * setuptools<81  — FTS/digitalpy import pkg_resources, removed in setuptools 81.
#   * requests       — a runtime dep FTS forgets to declare (it tries to self-pip3
#                      install it at start and fails on a venv without pip on PATH).
#   * opentelemetry==1.20.0 — digitalpy 0.3.13.x sets BatchSpanProcessor.span_exporter,
#                      which became a read-only property in opentelemetry>=~1.21,
#                      crashing startup. 1.20.0 is the last that works.
# =============================================================================
set -euo pipefail

VENV=/mnt/ssd/venvs/fts
export UV_CACHE_DIR=${UV_CACHE_DIR:-/mnt/ssd/caches/uv}
export TMPDIR=${TMPDIR:-/mnt/ssd/tmp}
mkdir -p "$TMPDIR" "$UV_CACHE_DIR"

command -v uv >/dev/null || { echo "uv not found; install uv first" >&2; exit 1; }

echo "=== creating $VENV (Python 3.11) ==="
uv venv --python 3.11 "$VENV"

echo "=== installing FreeTAKServer + verified pins ==="
uv pip install --python "$VENV/bin/python" \
  FreeTAKServer \
  'setuptools<81' \
  requests \
  'opentelemetry-api==1.20.0' 'opentelemetry-sdk==1.20.0' 'opentelemetry-semantic-conventions==0.41b0'

# Optional web UI (uncomment; pulls its own deps):
# uv pip install --python "$VENV/bin/python" FreeTAKServer-UI

echo "=== verifying imports ==="
"$VENV/bin/python" -c "import FreeTAKServer, pkg_resources, requests, opentelemetry; print('FTS deps OK')"

cat <<EOF

Done. Next:
  1. One-time sudo: point FTS's hardcoded /opt/fts at the SSD:
       sudo ln -sfn /mnt/ssd/data/fts /opt/fts
       sudo chown -h <svc-user>:<svc-user> /opt/fts && sudo install -d -o <svc-user> /mnt/ssd/data/fts
  2. Run it (env from flightctl/systemd/fts.env.example; FTS_FIRST_START=false skips the
     interactive wizard and boots headless on env+defaults):
       set -a; . /etc/flightctl/fts.env; set +a
       $VENV/bin/python -m FreeTAKServer.controllers.services.FTS
     CoT TCP comes up on :8087 (manually verified on-device with the meshsa gateway).
EOF
