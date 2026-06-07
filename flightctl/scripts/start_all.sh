#!/usr/bin/env bash
# =============================================================================
# start_all.sh — bring up the full flightctl edge-node stack in dependency order
# on the Jetson (JetPack 6.2, aarch64). Brings up, in order:
#
#   FreeTAKServer  ->  FTS Web UI  ->  WebMap (Node-RED)  ->  meshsa gateway
#   ->  mavlink2rest  ->  mavp2p  ->  MAVLink simulator
#
# ORDER MATTERS (two hard-won constraints, see flightctl/README.md):
#   1. udpc consumers (gateway :14551, mavlink2rest :14552) must be LISTENING
#      before mavp2p starts, or mavp2p's connected-UDP socket latches ECONNREFUSED
#      and the channel flaps forever. So we start those, wait for their binds,
#      THEN start mavp2p.
#   2. mavlink2rest only ingests MAVLink v2, so the simulator runs with MAVLINK20=1.
#      (pymavlink and the gateway parse v2 fine.)
#
# Runtime artifacts (binaries, venvs, Node) live on the SSD to spare the eMMC;
# override any path below via the environment. Run as your normal user (no sudo).
#
# Usage:
#   flightctl/scripts/start_all.sh start [--browser]   # default
#   flightctl/scripts/start_all.sh stop
#   flightctl/scripts/start_all.sh status
#   flightctl/scripts/start_all.sh restart [--browser]
# =============================================================================
set -uo pipefail

# --- paths / config (override via env) ---------------------------------------
SSD="${SSD:-/mnt/ssd}"
BIN="${FLIGHTCTL_BIN:-$SSD/flightctl/bin}"
LOGS="${FLIGHTCTL_LOGS:-$SSD/flightctl/logs}"
RUN="${FLIGHTCTL_RUN:-$SSD/flightctl/run}"
FTS_VENV="${FTS_VENV:-$SSD/venvs/fts}"
MESHSA_VENV="${MESHSA_VENV:-$SSD/venvs/meshsa}"
NODE_BIN="${NODE_BIN:-$SSD/node/node-v20.20.2-linux-arm64/bin}"
NODE_RED_USERDIR="${NODE_RED_USERDIR:-$SSD/data/node-red}"
FTS_DATA="${FTS_DATA:-$SSD/data/fts}"
FTS_ENV_FILE="${FTS_ENV_FILE:-$SSD/flightctl/fts.env}"
FTS_UI_DIR="${FTS_UI_DIR:-$FTS_VENV/lib/python3.11/site-packages/FreeTAKServer-UI}"

# repo flightctl/ dir (this script lives in flightctl/scripts/)
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLIGHTCTL_DIR="$(cd "$HERE/.." && pwd)"
GATEWAY_CONFIG="${GATEWAY_CONFIG:-$FLIGHTCTL_DIR/configs/jetson_gateway.proxy.json}"

# --- network endpoints (override via env) ------------------------------------
FTS_API_PORT="${FTS_API_PORT:-19023}"
FTS_COT_PORT="${FTS_COT_PORT:-8087}"
FTS_UI_PORT="${FTS_UI_PORT:-5000}"
WEBMAP_PORT="${WEBMAP_PORT:-1880}"
M2R_PORT="${M2R_PORT:-8088}"
MAVP2P_IN_PORT="${MAVP2P_IN_PORT:-14550}"      # udps: sim/autopilot dials in
GW_PORT="${GW_PORT:-14551}"                      # udpc -> meshsa gateway
M2R_UDP_PORT="${M2R_UDP_PORT:-14552}"            # udpc -> mavlink2rest
SIM_HZ="${SIM_HZ:-2}"

# WebMap (FreeTAKHub Node-RED flow) -> FTS
FTH_FTS_API_Auth="${FTH_FTS_API_Auth:-token}"   # default FTS SystemUser token; change for prod

OPEN_BROWSER=0
LAN_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"

# --- helpers -----------------------------------------------------------------
c_blue=$'\033[34m'; c_grn=$'\033[32m'; c_red=$'\033[31m'; c_dim=$'\033[2m'; c_off=$'\033[0m'
log()  { printf '%s[start-all]%s %s\n' "$c_blue" "$c_off" "$*"; }
ok()   { printf '%s[  ok   ]%s %s\n' "$c_grn" "$c_off" "$*"; }
err()  { printf '%s[ fail  ]%s %s\n' "$c_red" "$c_off" "$*" >&2; }

tcp_up() { ss -lnt 2>/dev/null | grep -q ":$1 "; }
udp_up() { ss -lnu 2>/dev/null | grep -q ":$1 "; }

# Export KEY=VALUE pairs from a systemd-style EnvironmentFile. Unlike `source`,
# this tolerates unquoted values containing spaces (e.g. FTS_CONNECTION_MESSAGE).
load_env_file() {
  [ -f "$1" ] || return 0
  local line key val
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in ''|\#*) continue;; esac
    key="${line%%=*}"; val="${line#*=}"
    [ "$key" = "$line" ] && continue   # no '=' on the line
    export "$key=$val"
  done < "$1"
}

# wait_port tcp|udp PORT NAME [timeout_s]
wait_port() {
  local proto="$1" port="$2" name="$3" timeout="${4:-30}" i=0
  while [ "$i" -lt "$timeout" ]; do
    if { [ "$proto" = tcp ] && tcp_up "$port"; } || { [ "$proto" = udp ] && udp_up "$port"; }; then
      ok "$name listening on $proto/$port"; return 0
    fi
    sleep 1; i=$((i+1))
  done
  err "$name did not come up on $proto/$port within ${timeout}s (see $LOGS/$name.log)"
  return 1
}

# start_svc NAME LOGFILE -- command...
start_svc() {
  local name="$1" logfile="$2"; shift 3   # drop NAME LOG --
  if [ -f "$RUN/$name.pid" ] && kill -0 "$(cat "$RUN/$name.pid" 2>/dev/null)" 2>/dev/null; then
    log "$name already running (pid $(cat "$RUN/$name.pid"))"; return 0
  fi
  log "starting $name ..."
  setsid "$@" >"$logfile" 2>&1 < /dev/null &
  echo $! > "$RUN/$name.pid"
}

open_url() { [ "$OPEN_BROWSER" = 1 ] && [ -n "${DISPLAY:-}" ] && \
  DISPLAY="$DISPLAY" setsid /snap/bin/chromium --new-window "$1" >/dev/null 2>&1 < /dev/null & }

# =============================================================================
do_start() {
  mkdir -p "$LOGS" "$RUN"

  # 1) FreeTAKServer (CoT :8087, REST API :19023) -----------------------------
  ( cd "$FTS_DATA" || exit 1
    load_env_file "$FTS_ENV_FILE"
    start_svc freetakserver "$LOGS/fts.log" -- \
      "$FTS_VENV/bin/python" -m FreeTAKServer.controllers.services.FTS )
  wait_port tcp "$FTS_COT_PORT" freetakserver 60 || true
  wait_port tcp "$FTS_API_PORT" freetakserver 60 || true

  # 2) FTS Web UI (:5000) -----------------------------------------------------
  ( cd "$FTS_UI_DIR" 2>/dev/null || { err "FTS-UI dir not found: $FTS_UI_DIR"; exit 0; }
    export FTS_IP=127.0.0.1 FTS_API_PORT="$FTS_API_PORT" FTS_API_PROTO=http \
           FTS_UI_EXPOSED_IP=0.0.0.0 FTS_UI_PORT="$FTS_UI_PORT" \
           FTS_UI_SQLALCHEMY_DATABASE_URI="sqlite:///$FTS_DATA/FTSServer-UI.db" \
           FTS_UI_WSKEY=YourWebsocketKey
    start_svc fts-ui "$LOGS/ftsui.log" -- "$FTS_VENV/bin/python" run.py )
  wait_port tcp "$FTS_UI_PORT" fts-ui 30 || true

  # 3) WebMap — FreeTAKHub Node-RED flow (:1880/tak-map) ----------------------
  ( export PATH="$NODE_BIN:$PATH" npm_config_cache="$SSD/node/npm-cache"
    export FTH_FTS_URL=127.0.0.1 FTH_FTS_TCP_Port="$FTS_COT_PORT" \
           FTH_FTS_API_Port="$FTS_API_PORT" FTH_FTS_API_Auth="$FTH_FTS_API_Auth" \
           FTH_FTS_EndPoints_geoObject_POST="ManageGeoObject/postGeoObject"
    start_svc webmap "$LOGS/webmap.log" -- \
      "$NODE_BIN/node-red" --userDir "$NODE_RED_USERDIR" "$NODE_RED_USERDIR/flows.json" )
  wait_port tcp "$WEBMAP_PORT" webmap 40 || true

  # 4) meshsa gateway — binds udpin:14551, bridges MAVLink->CoT->FTS ----------
  #    (must be listening BEFORE mavp2p connects its udpc)
  start_svc gateway "$LOGS/gateway.log" -- \
    env MESHSA_LOG_LEVEL="${MESHSA_LOG_LEVEL:-INFO}" \
    "$MESHSA_VENV/bin/python" -u "$FLIGHTCTL_DIR/run_gateway.py" --config "$GATEWAY_CONFIG"
  wait_port udp "$GW_PORT" gateway 20 || true

  # 5) mavlink2rest — binds udpin:14552, serves browser UI :8088 -------------
  #    (must be listening BEFORE mavp2p connects its udpc)
  start_svc mavlink2rest "$LOGS/mavlink2rest.log" -- \
    "$BIN/mavlink2rest" --connect="udpin:127.0.0.1:$M2R_UDP_PORT" --server="0.0.0.0:$M2R_PORT"
  wait_port udp "$M2R_UDP_PORT" mavlink2rest 20 || true

  # 6) mavp2p — router; udpc to the now-listening consumers -------------------
  start_svc mavp2p "$LOGS/mavp2p.log" -- \
    "$BIN/mavp2p" "udps:0.0.0.0:$MAVP2P_IN_PORT" \
    "udpc:127.0.0.1:$GW_PORT" "udpc:127.0.0.1:$M2R_UDP_PORT"
  wait_port udp "$MAVP2P_IN_PORT" mavp2p 20 || true

  # 7) MAVLink simulator — v2 (MAVLINK20=1) into the proxy -------------------
  #    Swap for a real autopilot by removing this and wiring serial: in mavp2p.
  start_svc sim "$LOGS/sim.log" -- \
    env MAVLINK20=1 "$MESHSA_VENV/bin/python" "$FLIGHTCTL_DIR/sim/mavlink_fake.py" \
    --endpoint "udpout:127.0.0.1:$MAVP2P_IN_PORT" --hz "$SIM_HZ"

  echo
  ok "stack up. URLs:"
  printf '   FTS Web UI    http://%s:%s/   (login admin/password)\n' "${LAN_IP:-127.0.0.1}" "$FTS_UI_PORT"
  printf '   WebMap        http://%s:%s/tak-map/\n' "${LAN_IP:-127.0.0.1}" "$WEBMAP_PORT"
  printf '   mavlink2rest  http://%s:%s/\n' "${LAN_IP:-127.0.0.1}" "$M2R_PORT"
  printf '   TAK/CoT       %s:%s  (point ATAK here)\n' "${LAN_IP:-127.0.0.1}" "$FTS_COT_PORT"
  if [ "$OPEN_BROWSER" = 1 ]; then
    open_url "http://127.0.0.1:$FTS_UI_PORT/"
    open_url "http://127.0.0.1:$WEBMAP_PORT/tak-map/"
    open_url "http://127.0.0.1:$M2R_PORT/"
  fi
}

do_stop() {
  # stop in reverse dependency order
  for name in sim mavp2p mavlink2rest gateway webmap fts-ui freetakserver; do
    local pf="$RUN/$name.pid"
    if [ -f "$pf" ]; then
      local pid; pid="$(cat "$pf" 2>/dev/null)"
      if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        log "stopping $name (pid $pid)"; kill "$pid" 2>/dev/null
        sleep 1; kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null
      fi
      rm -f "$pf"
    fi
  done
  # node-red spawns children; sweep by command for a clean stop
  pkill -f "node-red --userDir $NODE_RED_USERDIR" 2>/dev/null
  ok "stopped"
}

do_status() {
  printf '%-14s %-8s %s\n' SERVICE PID STATE
  for name in freetakserver fts-ui webmap gateway mavlink2rest mavp2p sim; do
    local pf="$RUN/$name.pid" pid="-" state="${c_red}down${c_off}"
    if [ -f "$pf" ]; then pid="$(cat "$pf" 2>/dev/null)"; fi
    if [ -n "$pid" ] && [ "$pid" != "-" ] && kill -0 "$pid" 2>/dev/null; then state="${c_grn}up${c_off}"; fi
    printf '%-14s %-8s %b\n' "$name" "$pid" "$state"
  done
  echo "${c_dim}ports:${c_off}"
  for p in "$FTS_COT_PORT tcp FTS-CoT" "$FTS_API_PORT tcp FTS-API" "$FTS_UI_PORT tcp FTS-UI" \
           "$WEBMAP_PORT tcp WebMap" "$M2R_PORT tcp mavlink2rest" \
           "$MAVP2P_IN_PORT udp mavp2p-in" "$GW_PORT udp gateway" "$M2R_UDP_PORT udp m2r-udp"; do
    set -- $p
    if { [ "$2" = tcp ] && tcp_up "$1"; } || { [ "$2" = udp ] && udp_up "$1"; }; then
      printf '   %s %-5s %s\n' "$c_grn✓$c_off" "$2/$1" "$3"
    else
      printf '   %s %-5s %s\n' "$c_red✗$c_off" "$2/$1" "$3"
    fi
  done
}

# --- dispatch ----------------------------------------------------------------
CMD="${1:-start}"; shift || true
for a in "$@"; do [ "$a" = "--browser" ] && OPEN_BROWSER=1; done
case "$CMD" in
  start)   do_start ;;
  stop)    do_stop ;;
  status)  do_status ;;
  restart) do_stop; sleep 2; do_start ;;
  *) echo "usage: $0 {start [--browser]|stop|status|restart [--browser]}" >&2; exit 2 ;;
esac
