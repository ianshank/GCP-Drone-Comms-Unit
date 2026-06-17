#!/usr/bin/env bash
# =============================================================================
# setup_pi5_node.sh  —  Pi 5 consolidated comms/TAK edge node (OpenMANET Route A)
# Raspberry Pi OS Lite 64-bit (Bookworm). Run as a sudo-capable user.
#
# Roles installed: HaLow 802.11s + batman-adv mesh gate, FreeTAKServer (Docker),
# TAK Meshtastic Gateway, ADS-B->CoT (dump1090 + adsbcot), dnsmasq, hostapd AP.
#
# !!! READ FIRST !!!
#  * The HaLow (Morse Micro) driver is NOT installed here — install it per Seeed's
#    wiki and CONFIRM it builds against your Pi 5 kernel before running this.
#  * Verify every CONFIG value below against your hardware/region.
#  * Review before running. This edits network config and enables services.
# =============================================================================
set -euo pipefail

# ----------------------------- CONFIG (EDIT ME) ------------------------------
HALOW_IF="wlan1"            # HaLow interface (check: iw dev)
MESH_ID="openmanet"
HALOW_FREQ="9050"           # kHz/MHz per your region+bandwidth — VERIFY (US 902-928)
NODE_IP="10.41.254.1"       # this node, safe static range OpenMANET reserves
MESH_CIDR="16"
UPLINK_IF="eth0"            # interface that reaches the internet/LAN (gateway NAT)
LAN_IF="eth0"              # iface the Jetson plugs into (can equal UPLINK_IF w/ care)
AP_IF="wlan0"              # Pi 5 built-in Wi-Fi as the ATAK client AP
AP_SSID="gcs-mesh"
AP_PSK="change-me-please"
FTS_IP="${NODE_IP}"        # FreeTAKServer bind/host IP on the mesh
COUNTRY="US"
MESH_USER="$(whoami)"
# -----------------------------------------------------------------------------

echo "[*] Base packages"
sudo apt update
sudo apt install -y batctl iw wpasupplicant dnsmasq hostapd \
  build-essential dkms git rtl-sdr python3-venv python3-pip \
  docker.io docker-compose-plugin
sudo systemctl enable --now docker

echo "[*] Python venvs for the gateway + adsbcot"
python3 -m venv "$HOME/tmg"
"$HOME/tmg/bin/pip" install --upgrade pip
"$HOME/tmg/bin/pip" install git+https://github.com/snstac/takproto@refs/pull/16/merge
"$HOME/tmg/bin/pip" install tak-meshtastic-gateway

python3 -m venv "$HOME/adsb"
"$HOME/adsb/bin/pip" install --upgrade pip
"$HOME/adsb/bin/pip" install adsbcot

echo "[*] dump1090 (ADS-B). If dump1090-fa isn't packaged, build readsb/dump1090-mutability."
sudo apt install -y dump1090-mutability || echo "  (install a dump1090 variant manually)"

echo "[*] FreeTAKServer via Docker compose -> /opt/fts"
# Pin to a verified release for reproducible installs; `:latest` drifts on every
# upstream push. Override: FTS_IMAGE=ghcr.io/freetakteam/freetakserver:<tag>
# TODO(pin): replace the default with a known-good FTS release tag.
FTS_IMAGE="${FTS_IMAGE:-ghcr.io/freetakteam/freetakserver:latest}"
sudo mkdir -p /opt/fts && sudo tee /opt/fts/docker-compose.yml >/dev/null <<YML
services:
  fts:
    image: ${FTS_IMAGE}
    network_mode: host
    restart: unless-stopped
    environment:
      - FTS_IP=${FTS_IP}
    volumes:
      - /opt/fts/data:/opt/fts
YML

echo "[*] Install mesh-up script"
sudo install -m 0755 "$(dirname "$0")/mesh-up.sh" /usr/local/sbin/mesh-up.sh

echo "[*] Write /etc/default/mesh-node (env for units + mesh-up)"
sudo tee /etc/default/mesh-node >/dev/null <<ENV
HALOW_IF=${HALOW_IF}
MESH_ID=${MESH_ID}
HALOW_FREQ=${HALOW_FREQ}
NODE_IP=${NODE_IP}
MESH_CIDR=${MESH_CIDR}
UPLINK_IF=${UPLINK_IF}
COUNTRY=${COUNTRY}
ENV

echo "[*] dnsmasq: lease 10.41.x.x on bat0 + LAN (Jetson)"
sudo tee /etc/dnsmasq.d/mesh.conf >/dev/null <<CONF
interface=bat0
interface=${LAN_IF}
bind-interfaces
dhcp-range=10.41.10.50,10.41.10.250,255.255.0.0,12h
dhcp-option=3,${NODE_IP}
dhcp-option=6,${NODE_IP}
CONF

echo "[*] hostapd: ATAK client AP on ${AP_IF}"
sudo tee /etc/hostapd/hostapd.conf >/dev/null <<CONF
interface=${AP_IF}
driver=nl80211
ssid=${AP_SSID}
hw_mode=g
channel=6
wpa=2
wpa_passphrase=${AP_PSK}
wpa_key_mgmt=WPA-PSK
rsn_pairwise=CCMP
country_code=${COUNTRY}
CONF
sudo sed -i 's|^#DAEMON_CONF=.*|DAEMON_CONF="/etc/hostapd/hostapd.conf"|' /etc/default/hostapd || true

echo "[*] systemd unit: mesh-up (HaLow + batman + addressing + NAT)"
sudo tee /etc/systemd/system/mesh-up.service >/dev/null <<'UNIT'
[Unit]
Description=HaLow 802.11s + batman-adv mesh bring-up
Wants=network-pre.target
Before=dnsmasq.service hostapd.service
After=sys-subsystem-net-devices-wlan1.device
[Service]
Type=oneshot
RemainAfterExit=yes
EnvironmentFile=/etc/default/mesh-node
ExecStart=/usr/local/sbin/mesh-up.sh
[Install]
WantedBy=multi-user.target
UNIT

echo "[*] systemd unit: TAK Meshtastic Gateway"
sudo tee /etc/systemd/system/tak-gateway.service >/dev/null <<UNIT
[Unit]
Description=TAK Meshtastic Gateway
After=mesh-up.service network-online.target
Wants=network-online.target
[Service]
ExecStart=${HOME}/tmg/bin/tak-meshtastic-gateway
Restart=always
RestartSec=3
User=${MESH_USER}
[Install]
WantedBy=multi-user.target
UNIT

echo "[*] systemd unit: adsbcot (ADS-B -> CoT to FTS)"
sudo tee /etc/systemd/system/adsbcot.service >/dev/null <<UNIT
[Unit]
Description=ADS-B to CoT feed
After=mesh-up.service
[Service]
Environment=COT_URL=tcp://${FTS_IP}:8087
Environment=FEED_URL=tcp+beast://127.0.0.1:30005
ExecStart=${HOME}/adsb/bin/adsbcot
Restart=always
RestartSec=5
User=${MESH_USER}
[Install]
WantedBy=multi-user.target
UNIT

echo "[*] Enable services"
sudo systemctl daemon-reload
sudo systemctl enable mesh-up.service dnsmasq hostapd tak-gateway.service adsbcot.service
sudo systemctl unmask hostapd || true

echo "[*] Bring up FreeTAKServer"
cd /opt/fts && sudo docker compose up -d

cat <<DONE

[✓] Provisioning complete (services enabled, start on next boot).
    Start now with:  sudo systemctl start mesh-up tak-gateway adsbcot
    FreeTAKServer UI: http://${FTS_IP}:5000  (change default creds)
    Jetson: plug into ${LAN_IF}; it will lease a 10.41.x.x and route via this node.

    STILL TO DO:
      1. Install the Morse Micro HaLow driver (Seeed wiki) + confirm ${HALOW_IF} appears.
      2. Verify HALOW_FREQ / channel + bandwidth for your region.
      3. Point ATAK clients (on ${AP_SSID}) at tcp://${FTS_IP}:8087 or the FTS data package.
      4. Mind 900 MHz coexistence: HaLow + 915 LoRa + LR900.
DONE
