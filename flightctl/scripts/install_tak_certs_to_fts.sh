#!/usr/bin/env bash
# =============================================================================
# install_tak_certs_to_fts.sh — replace FreeTAKServer's PKI with the meshsa CA
# so TLS CoT on :8089 presents a SAN-bearing cert the gateway can fully verify.
#
# WHY: FTS ships a self-signed server cert with NO SubjectAltName, so a TLS client
# doing hostname verification (the gateway with tls_verify=true) cannot validate
# it. gen_tak_certs.sh produces a server cert with SAN IP:127.0.0.1 (+ the LAN IP);
# this script installs it (and the matching CA) into FTS's certs dir.
#
# ⚠️  DISRUPTIVE / OUTWARD-FACING:
#   * Requires an FTS restart to take effect.
#   * Replaces FTS's CA, so EXISTING ATAK client packages (signed by the old CA)
#     stop trusting the server — re-issue client.p12 + ca.crt to field clients.
#   Back up first (this script does), and run only with operator approval.
#
# Env (defaults match gen_tak_certs.sh staged onto the SSD):
#   SRC_CERTS   dir holding ca.crt/server.crt/server.key  (default: /mnt/ssd/flightctl/certs)
#   FTS_CERTS   FreeTAKServer certs dir                    (default: /mnt/ssd/data/fts/certs)
# =============================================================================
set -euo pipefail

SRC_CERTS="${SRC_CERTS:-/mnt/ssd/flightctl/certs}"
FTS_CERTS="${FTS_CERTS:-/mnt/ssd/data/fts/certs}"

for f in ca.crt server.crt server.key; do
  [ -f "$SRC_CERTS/$f" ] || { echo "error: missing $SRC_CERTS/$f (run gen_tak_certs.sh)" >&2; exit 1; }
done
[ -d "$FTS_CERTS" ] || { echo "error: FTS certs dir not found: $FTS_CERTS" >&2; exit 1; }

# 1. Back up the existing FTS PKI (timestamped, never overwritten).
BACKUP="$FTS_CERTS/backup-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$BACKUP"
cp -a "$FTS_CERTS"/*.pem "$FTS_CERTS"/*.key "$BACKUP"/ 2>/dev/null || true
echo "backed up existing FTS certs -> $BACKUP"

# 2. Install our PKI under the filenames FTS's MainConfig expects.
install -m 0644 "$SRC_CERTS/server.crt" "$FTS_CERTS/server.pem"
install -m 0600 "$SRC_CERTS/server.key" "$FTS_CERTS/server.key"
install -m 0600 "$SRC_CERTS/server.key" "$FTS_CERTS/server.key.unencrypted"
install -m 0644 "$SRC_CERTS/ca.crt"     "$FTS_CERTS/ca.pem"

echo "installed meshsa PKI into $FTS_CERTS (server.pem/server.key/ca.pem)"
echo "NOW: restart FreeTAKServer, then verify with:"
echo "  GATEWAY_CONFIG=flightctl/configs/jetson_gateway.tls.json flightctl/scripts/start_all.sh restart"
echo "Re-issue $SRC_CERTS/client.p12 + ca.crt to any ATAK clients (old CA no longer trusted)."
