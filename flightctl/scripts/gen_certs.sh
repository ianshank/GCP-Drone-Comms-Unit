#!/usr/bin/env bash
# =============================================================================
# gen_certs.sh — TEMPLATE. Generate a self-signed CA, a FreeTAKServer server cert,
# and a client cert, then bundle an ATAK data-package zip a tablet can import.
#
# This is an edit-before-running template: set CN/SAN and OUT_DIR to your unit's
# real LAN identity. Nothing here is committed as a real key — keys are generated
# locally and live under OUT_DIR (keep them OUT of the repo / out of version control).
#
# Layout produced under OUT_DIR:
#   ca.pem               — CA cert (trust anchor; give to gateway + FTS + ATAK)
#   ca.key               — CA private key (keep secret)
#   server.pem           — FTS server cert chain (key + cert)
#   gateway-client.pem   — meshsa gateway client cert chain (key + cert)
#   atak.p12 + datapackage/  — ATAK client identity + importable data-package zip
#
# The gateway consumes ca.pem + gateway-client.pem via the tak_tcp transport
# options (see flightctl/configs/jetson_gateway.tls.json). FreeTAKServer consumes
# server.pem + ca.pem (see FTS_CERTS_PATH / FTS_SSLCOT_PORT in fts.env.example).
# =============================================================================
set -euo pipefail

# --- EDIT THESE before running -----------------------------------------------
OUT_DIR="${OUT_DIR:-/etc/flightctl/certs}"   # where keys/certs land (NOT the repo)
SERVER_CN="${SERVER_CN:-freetakserver}"      # must match tls_server_hostname / SAN
SERVER_SAN="${SERVER_SAN:-DNS:freetakserver,IP:127.0.0.1}"  # add the Jetson LAN IP
CLIENT_CN="${CLIENT_CN:-gateway-client}"
ATAK_CN="${ATAK_CN:-atak-user}"
P12_PASS="${P12_PASS:-atakatak}"             # ATAK default import password
DAYS="${DAYS:-3650}"
# -----------------------------------------------------------------------------

command -v openssl >/dev/null || { echo "openssl not found" >&2; exit 1; }
umask 077
mkdir -p "$OUT_DIR/datapackage/certs"
cd "$OUT_DIR"

echo "[1/5] CA"
openssl req -x509 -newkey rsa:4096 -nodes -keyout ca.key -out ca.pem \
  -days "$DAYS" -subj "/CN=flightctl-CA"

gen_leaf() {  # $1=name  $2=CN  $3=SAN(optional)
  local name="$1" cn="$2" san="${3:-}"
  openssl req -newkey rsa:4096 -nodes -keyout "$name.key" -out "$name.csr" -subj "/CN=$cn"
  if [ -n "$san" ]; then
    openssl x509 -req -in "$name.csr" -CA ca.pem -CAkey ca.key -CAcreateserial \
      -out "$name.crt" -days "$DAYS" -extfile <(printf "subjectAltName=%s" "$san")
  else
    openssl x509 -req -in "$name.csr" -CA ca.pem -CAkey ca.key -CAcreateserial \
      -out "$name.crt" -days "$DAYS"
  fi
  cat "$name.key" "$name.crt" > "$name.pem"   # combined chain for load_cert_chain
  rm -f "$name.csr"
}

echo "[2/5] server cert ($SERVER_CN)"
gen_leaf server "$SERVER_CN" "$SERVER_SAN"

echo "[3/5] gateway client cert ($CLIENT_CN)"
gen_leaf gateway-client "$CLIENT_CN"

echo "[4/5] ATAK client identity ($ATAK_CN)"
gen_leaf atak "$ATAK_CN"
openssl pkcs12 -export -in atak.crt -inkey atak.key -certfile ca.pem \
  -name "$ATAK_CN" -passout "pass:$P12_PASS" -out atak.p12

echo "[5/5] ATAK data-package zip"
cp ca.pem atak.p12 datapackage/certs/
# Minimal MANIFEST + connection pref so ATAK auto-imports the cert + server entry.
cat > datapackage/MANIFEST/manifest.xml <<'XML' 2>/dev/null || mkdir -p datapackage/MANIFEST && cat > datapackage/MANIFEST/manifest.xml <<'XML'
<MissionPackageManifest version="2">
  <Configuration>
    <Parameter name="uid" value="flightctl-tls"/>
    <Parameter name="name" value="flightctl-tls.zip"/>
  </Configuration>
  <Contents>
    <Content ignore="false" zipEntry="certs/ca.pem"/>
    <Content ignore="false" zipEntry="certs/atak.p12"/>
  </Contents>
</MissionPackageManifest>
XML
( cd datapackage && zip -qr ../flightctl-tls.zip . )

echo
echo "Done. Gateway:  tls_cafile=$OUT_DIR/ca.pem  tls_certfile=$OUT_DIR/gateway-client.pem"
echo "      FTS:      server.pem + ca.pem under FTS_CERTS_PATH; FTS_SSLCOT_PORT=8089"
echo "      ATAK:     import $OUT_DIR/flightctl-tls.zip (p12 password: $P12_PASS)"
