#!/usr/bin/env bash
# =============================================================================
# gen_tak_certs.sh — generate a CA -> server -> client PKI for TLS CoT (:8089).
#
# Produces the certificates the TLS-enabled TakTcpTransport + FreeTAKServer need,
# plus a client PKCS#12 for ATAK data-package import. Self-signed CA: meant for
# closed/field deployments, not a public PKI. Nothing is hard-coded — every value
# is an env var with a default:
#
#   OUT_DIR        output directory                      (default: flightctl/certs)
#   CA_CN          CA common name                        (default: meshsa-tak-ca)
#   SERVER_CN      server cert CN (the FTS hostname/IP)  (default: takserver)
#   SERVER_SAN     server SubjectAltName                 (default: DNS:${SERVER_CN})
#   CLIENT_CN      client cert CN (the operator/unit)    (default: meshsa-client)
#   DAYS           validity in days                      (default: 825)
#   P12_PASS       PKCS#12 export passphrase             (default: atakatak)
#
# The output dir is git-ignored: private keys must never be committed. Point the
# transport at the results via options: tls=true, tls_ca_cert=<OUT_DIR>/ca.crt,
# tls_client_cert=<OUT_DIR>/client.crt, tls_client_key=<OUT_DIR>/client.key.
# Import <OUT_DIR>/client.p12 + ca.crt into ATAK (Settings -> Network Preferences
# -> Manage Server Connections / import the data package).
# =============================================================================
set -euo pipefail

if ! command -v openssl >/dev/null 2>&1; then
  echo "error: openssl not found on PATH" >&2
  exit 1
fi

OUT_DIR="${OUT_DIR:-flightctl/certs}"
CA_CN="${CA_CN:-meshsa-tak-ca}"
SERVER_CN="${SERVER_CN:-takserver}"
SERVER_SAN="${SERVER_SAN:-DNS:${SERVER_CN}}"
CLIENT_CN="${CLIENT_CN:-meshsa-client}"
DAYS="${DAYS:-825}"
P12_PASS="${P12_PASS:-atakatak}"

# Create keys 0600 from the start: on a multi-user host a private key must not be
# world-readable even briefly between creation and a later chmod.
umask 077

mkdir -p "${OUT_DIR}"
chmod 700 "${OUT_DIR}"

# 1. Certificate authority (self-signed root).
openssl req -x509 -nodes -newkey rsa:4096 -sha256 -days "${DAYS}" \
  -keyout "${OUT_DIR}/ca.key" -out "${OUT_DIR}/ca.crt" \
  -subj "/CN=${CA_CN}"

# 2. Server certificate (signed by the CA, with a SubjectAltName for hostname
#    verification). The SAN is required: clients verifying the hostname reject a
#    cert without a matching SAN.
openssl req -nodes -newkey rsa:4096 -sha256 \
  -keyout "${OUT_DIR}/server.key" -out "${OUT_DIR}/server.csr" \
  -subj "/CN=${SERVER_CN}"
openssl x509 -req -in "${OUT_DIR}/server.csr" -sha256 -days "${DAYS}" \
  -CA "${OUT_DIR}/ca.crt" -CAkey "${OUT_DIR}/ca.key" -CAcreateserial \
  -extfile <(printf 'subjectAltName=%s\n' "${SERVER_SAN}") \
  -out "${OUT_DIR}/server.crt"

# 3. Client certificate (signed by the CA) for mutual-TLS / operator identity.
openssl req -nodes -newkey rsa:4096 -sha256 \
  -keyout "${OUT_DIR}/client.key" -out "${OUT_DIR}/client.csr" \
  -subj "/CN=${CLIENT_CN}"
openssl x509 -req -in "${OUT_DIR}/client.csr" -sha256 -days "${DAYS}" \
  -CA "${OUT_DIR}/ca.crt" -CAkey "${OUT_DIR}/ca.key" -CAcreateserial \
  -out "${OUT_DIR}/client.crt"

# 4. Client PKCS#12 bundle for ATAK import (cert + key + CA chain).
openssl pkcs12 -export -name "${CLIENT_CN}" \
  -inkey "${OUT_DIR}/client.key" -in "${OUT_DIR}/client.crt" \
  -certfile "${OUT_DIR}/ca.crt" -passout "pass:${P12_PASS}" \
  -out "${OUT_DIR}/client.p12"

chmod 600 "${OUT_DIR}"/*.key
# Drop intermediate CSRs and the CA serial file — keep only keys/certs/p12.
rm -f "${OUT_DIR}"/*.csr "${OUT_DIR}"/*.srl

echo "PKI written to ${OUT_DIR}:"
echo "  ca.crt / ca.key            (root CA)"
echo "  server.crt / server.key    (point FreeTAKServer TLS :8089 at these)"
echo "  client.crt / client.key    (transport: tls_client_cert / tls_client_key)"
echo "  client.p12                 (import into ATAK; passphrase: ${P12_PASS})"
echo "transport options: tls=true tls_ca_cert=${OUT_DIR}/ca.crt"
