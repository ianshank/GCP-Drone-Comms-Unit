#!/usr/bin/env bash
# mesh-up.sh — bring up HaLow 802.11s + batman-adv, address bat0, NAT to uplink.
# Invoked by mesh-up.service. Reads /etc/default/mesh-node.
# VERIFY the HaLow mesh mode: if the Morse driver lacks 802.11s mesh-point,
# fall back to IBSS (see the commented block).
set -euo pipefail
[ -f /etc/default/mesh-node ] && . /etc/default/mesh-node

: "${HALOW_IF:=wlan1}"; : "${MESH_ID:=openmanet}"; : "${HALOW_FREQ:=9050}"
: "${NODE_IP:=10.41.254.1}"; : "${MESH_CIDR:=16}"; : "${UPLINK_IF:=eth0}"
: "${COUNTRY:=US}"

modprobe batman-adv
iw reg set "$COUNTRY" || true

# --- HaLow as 802.11s mesh point ---
ip link set "$HALOW_IF" down || true
iw dev "$HALOW_IF" set type mp
ip link set "$HALOW_IF" up
iw dev "$HALOW_IF" mesh join "$MESH_ID" freq "$HALOW_FREQ"

# --- Fallback: IBSS instead of 802.11s (uncomment if driver lacks 11s) ---
# iw dev "$HALOW_IF" set type ibss
# ip link set "$HALOW_IF" up
# iw dev "$HALOW_IF" ibss join "$MESH_ID" "$HALOW_FREQ"

# --- batman-adv over the HaLow link; IP lives on bat0 ---
batctl if add "$HALOW_IF"
ip link set up dev bat0
ip addr flush dev bat0 || true
ip addr add "${NODE_IP}/${MESH_CIDR}" dev bat0

# --- Mesh Gate: forward + NAT to the uplink ---
sysctl -w net.ipv4.ip_forward=1
iptables -t nat -C POSTROUTING -o "$UPLINK_IF" -j MASQUERADE 2>/dev/null \
  || iptables -t nat -A POSTROUTING -o "$UPLINK_IF" -j MASQUERADE

echo "mesh-up: ${HALOW_IF} -> bat0 ${NODE_IP}/${MESH_CIDR}, NAT via ${UPLINK_IF}"
