# flightctl — flight-control + TAK edge node (ops)

Ops assets that turn this Jetson into a flight-control + TAK edge node on top of the
`meshsa` framework: a MAVLink proxy, a TAK server (FreeTAKServer), Betaflight tooling,
and the glue that bridges drone/FC telemetry to ATAK clients as Cursor-on-Target tracks.

The meshsa integration is **code-complete and tested** (a `telemetry` codec + a
`mavlink_source` transport, bridged to the existing `cot`/`tak` path). What lives here is
the deployment/runtime layer. See the approved plan for the full design and sequencing.

## Layout
| Path | What |
| ---- | ---- |
| `scripts/start_all.sh` | **One-command bring-up** of the whole stack in dependency order (`start`/`stop`/`status`/`restart`). No sudo. |
| `scripts/relocate_to_ssd.sh` | **Phase 1** — conservative eMMC→SSD relocation (Docker data-root, caches, mount hardening, cleanup). **Run with sudo after reviewing.** |
| `configs/jetson_gateway.json` | Example meshsa node: `mavlink_source`(telemetry) → `tak_tcp`(cot, air type). Direct (no proxy): MAVLink in on `udpin:…:14550`. |
| `configs/jetson_gateway.proxy.json` | Same node behind the mavp2p proxy: MAVLink in on `udpin:127.0.0.1:14551` (mavp2p fans the autopilot stream to the gateway, mavlink2rest, and any GCS). Used by `start_all.sh` (default `FC_MODE=sim`). |
| `configs/jetson_gateway.msp.json` | Real **Betaflight FC over USB**: `msp_source`(telemetry) → `tak_tcp`/`tak_multicast`(cot). Used by `start_all.sh` when `FC_MODE=msp`. See [Real Betaflight FC over USB](#real-betaflight-fc-over-usb-msp-mode). |
| `rc_bridge.py` + `configs/jetson_rc.json` | **Pilot the FC from the Jetson** (joystick → MSP RC) + telemetry. Used by `start_all.sh` when `FC_MODE=pilot`. See [Pilot from the Jetson](#pilot-from-the-jetson-msp-rc). |
| `configs/jetson_gateway.tls.json` | Node that talks **TLS CoT** to FreeTAKServer `:8089` (client cert) with outbound **pacing** — see [TLS CoT + pacing](#tls-cot--rate-limit-pacing). |
| `scripts/gen_certs.sh` | **Template** — generate a CA + server + client certs and an importable ATAK data-package zip. Edit CN/SAN/`OUT_DIR` before running. |
| `sim/mavlink_fake.py` | pymavlink `udpout` simulator — emits HEARTBEAT + GLOBAL_POSITION_INT for dev/e2e (no autopilot needed). |
| `systemd/mavp2p.service` + `mavp2p.env.example` | MAVLink proxy (mavp2p) unit. |
| `systemd/freetakserver.service` + `fts.env.example` | FreeTAKServer unit (Python 3.11 venv). |
| `udev/99-flightctl-serial.rules.example` | Stable `/dev/flightctl-*` serial symlinks for autopilot/FC. |

## Bring up the whole stack (one command)

Once the prerequisites are staged on the SSD (mavp2p binary, the `meshsa`/`fts` venvs,
Node 20 + Node-RED for the WebMap, and `mavlink2rest`), start everything in the correct
dependency order:

```bash
flightctl/scripts/start_all.sh start          # add --browser to open the web UIs
flightctl/scripts/start_all.sh status         # per-service pid + port health
flightctl/scripts/start_all.sh stop
```

Order is: **FreeTAKServer → FTS Web UI → WebMap → meshsa gateway → mavlink2rest → mavp2p
→ simulator**, with a readiness wait on each. Paths/ports are env-overridable at the top of
the script. By default it runs the bundled MAVLink **simulator**; for real hardware, drop the
sim and point mavp2p at `serial:/dev/flightctl-autopilot:<baud>`.

### Endpoints it exposes

| UI / service | URL / endpoint | Notes |
| ------------ | -------------- | ----- |
| TAK / CoT (ATAK) | `<jetson-ip>:8087` | point ATAK's TAK Server stream here |
| FreeTAKServer Web UI | `http://<jetson-ip>:5000/` | admin dashboard; default login `admin` / `password` (change for prod) |
| WebMap (Node-RED worldmap) | `http://<jetson-ip>:1880/tak-map/` | FreeTAKHub flow; in-browser moving map of CoT tracks |
| mavlink2rest | `http://<jetson-ip>:8088/` | browser/REST/WS view of the raw MAVLink stream off the proxy |

> **MAVLink GCS UI:** `mavp2p` has no native UI. mavlink2rest is the browser GCS here;
> QGroundControl ships **x86_64 only** (no arm64), and the MAVProxy map/HUD GUI needs
> `python3-wxgtk4.0` (apt/sudo).

### Two wiring gotchas (encoded in `start_all.sh`)

1. **Start order.** mavp2p's `udpc` outputs are *connected* UDP sockets — each consumer
   (gateway `:14551`, mavlink2rest `:14552`) must be **listening before mavp2p starts**, or
   mavp2p latches `ECONNREFUSED` and the channel flaps. The script binds the consumers first.
2. **MAVLink v2 only.** `mavlink2rest` ignores MAVLink v1, so the simulator runs with
   `MAVLINK20=1` (pymavlink and the gateway parse v2 fine). Sim is system id `1`, component `0`.

## Real Betaflight FC over USB (MSP mode)

A Betaflight FC speaks **MSP**, not MAVLink, so it has its own path: the `msp_source`
transport polls the FC over the USB serial VCP and feeds the same `telemetry → cot/tak`
chain. Run it with `FC_MODE=msp` — the gateway polls the FC directly, and the
MAVLink-only services (sim, mavp2p, mavlink2rest) are skipped:

```bash
FC_MODE=msp flightctl/scripts/start_all.sh start     # add --browser for the web UIs
FC_MODE=msp flightctl/scripts/start_all.sh status
FC_MODE=msp flightctl/scripts/start_all.sh stop
```

Config: `configs/jetson_gateway.msp.json` (FC → `tak_tcp` :8087 + `tak_multicast`).
The FC shows up as the **`FC1`** track in ATAK / WebMap / the FTS UI.

- **No GPS? It still appears.** A GPS-less bench FC has no position, so set
  `fallback_lat`/`fallback_lon` (decimal degrees, the FC's location) in the config —
  that places the track. A real GPS fix, when present, always overrides the fallback.
  Remove the `fallback_*` keys to suppress the track until a fix arrives. **Edit the
  placeholder `0.0/0.0` coordinates in `jetson_gateway.msp.json` before use.**
- **Live telemetry as remarks.** The poll also reads battery voltage, current, RSSI
  (`MSP_ANALOG`) and attitude (`MSP_ATTITUDE`); present fields render into the track's
  CoT `<remarks>` (e.g. `VBAT 11.8V RSSI 1023 ROLL 2`).
- **Stable device name (one-time, sudo).** USB enumeration is non-deterministic; install
  the udev rule so the FC is always `/dev/flightctl-fc` (the config's default `device`).
  The bundled rule already matches Betaflight's `0483:5740`:

  ```bash
  sudo cp flightctl/udev/99-flightctl-serial.rules.example \
          /etc/udev/rules.d/99-flightctl-serial.rules
  sudo udevadm control --reload && sudo udevadm trigger
  sudo usermod -aG dialout "$USER"   # open the port without sudo (re-login to apply)
  ```

  To skip udev entirely, set `"device": "/dev/ttyACM0"` in the config.
- **Serial is exclusive — one user at a time.** Betaflight Configurator (WebSerial) and
  the gateway's `yamspy` poller both need exclusive access to the FC's serial port; they
  **cannot run together**. Workflow: configure/tune in the Configurator
  (`/snap/bin/chromium` → `https://app.betaflight.com`) → **Disconnect** → then start
  `FC_MODE=msp`. Confirm battery and RSSI sources are configured in Betaflight so those
  remarks have data.

## Pilot from the Jetson (MSP RC)

`FC_MODE=pilot` flies the FC **from the Jetson over USB**: `rc_bridge.py` reads the
RadioMaster/EdgeTX radio at `/dev/input/js0` (USB-joystick mode), maps the sticks/switches
to RC channels, and streams `MSP_SET_RAW_RC` to the FC — while the *same* serial handle is
decimated to also poll telemetry and publish the FC's CoT track. One process owns the one
exclusive FC serial, so this **cannot run with `FC_MODE=msp`** (both want the port). This is
a **bench / HITL** path (USB-tethered, no range) — a precursor to ELRS and a reusable
computer-in-the-loop seam; for real flight, use the ELRS RF link.

> 🚨 **SAFETY — PROPS OFF.** This drives real motors. The bridge starts **disarmed /
> throttle-min**, **never auto-arms** (the arm switch must be seen released once first),
> **fails safe** (disarm + throttle-min) on stale joystick input, and **disarms on shutdown**.
> Always `--dry-run` first.

**Betaflight setup (Configurator, then Disconnect):** Receiver tab → Serial RX provider =
**MSP**; set the channel map (AETR) and **failsafe**; map **ARM** to the AUX the bridge drives
(`arm.channel` in the mapping). Confirm battery/RSSI sources so the telemetry remarks have data.

```bash
# 1) Calibrate the mapping with NO writes to the FC — move each stick/switch, watch channels:
rc_bridge.py --dry-run --mapping flightctl/configs/jetson_rc.json
#    Edit configs/jetson_rc.json (axis/button indices are hardware-specific) until correct.

# 2) Prove the FC sees the channels (sends RC + logs MSP_RC read-back; no Configurator):
rc_bridge.py --device /dev/flightctl-fc --monitor

# 3) Full: pilot + telemetry track to FTS (props off!):
FC_MODE=pilot flightctl/scripts/start_all.sh start    # FC1 track appears at :1880/tak-map
```

`jetson_rc.json` is an `RcMapping`: channels in MSP order `[roll, pitch, yaw, throttle,
aux…]`; each channel is an `axis`, a `button` (2-pos), or `buttons` (N-position group, e.g. a
3-pos mode switch → 1000/1500/2000). `arm.source_button` must be a **toggle** switch, not a
momentary button. Override `RC_DEVICE`/`RC_JS`/`RC_MAPPING`/`RC_FALLBACK_LAT`/`RC_FALLBACK_LON`
via env. Like MSP mode, the FC serial needs `dialout` group membership.

## TLS CoT + rate-limit pacing

For a hardened FreeTAKServer, the `tak_tcp` transport can talk TLS CoT (default
`:8089`) with a client cert, and pace outbound tracks so a fast source doesn't
overrun FTS. Both are config-driven and **off by default** — plain `:8087` is
unchanged. See `configs/jetson_gateway.tls.json` for a complete example.

```jsonc
// transport "options" for the tak_tcp entry:
"options": {
  "host": "127.0.0.1", "port": 8089,
  "tls": true,
  "tls_cafile":   "/etc/flightctl/certs/ca.pem",            // trust anchor
  "tls_certfile": "/etc/flightctl/certs/gateway-client.pem", // client key+chain (combined PEM)
  "tls_server_hostname": "freetakserver",                   // must match the server cert SAN
  // "tls_verify": false,        // closed dev net only — disables cert verification
  "pace_min_interval_s": 0.2     // >=0.2 s between CoT frames (0 = unpaced)
}
```

**Generate certs + the ATAK data-package** (edit the CN/SAN/`OUT_DIR` first):

```bash
OUT_DIR=/etc/flightctl/certs SERVER_SAN="DNS:freetakserver,IP:<jetson-lan-ip>" \
  bash flightctl/scripts/gen_certs.sh
```

This writes `ca.pem` + `server.pem` (for FTS, under `FTS_CERTS_PATH`; FTS serves TLS
on `FTS_SSLCOT_PORT=8089`), `gateway-client.pem` (for the gateway options above), and
`flightctl-tls.zip` — import that data-package into ATAK (default p12 password
`atakatak`) to trust the CA and load the client identity. Keep all keys **out of the
repo**.

## Quick local test (no hardware, no services) — works today
```bash
# the meshsa SSD venv already has pymavlink? if not: uv pip install pymavlink (after Phase 1)
cd packages/meshsa && /mnt/ssd/venvs/meshsa/bin/python -m pytest -q   # 181 tests, 100% cov
```

## What is already done vs. what needs root

**Done & verified (no sudo, all on the SSD):** branch + code + 181 tests at 100% cov;
`mavp2p` v1.3.3 arm64 staged at `/mnt/ssd/flightctl/bin/mavp2p`; `pymavlink`+`yamspy`
installed in `/mnt/ssd/venvs/meshsa` (live MAVLink→CoT run confirmed); FreeTAKServer
installed in a uv-built Python-3.11 venv at `/mnt/ssd/venvs/fts` (entrypoint
`python -m FreeTAKServer.controllers.services.FTS`).

**Sudo punch-list (the only root-required steps):**
```bash
# 1. Free/relocate the 97%-full eMMC (Docker data-root, caches, mount hardening)
sudo bash flightctl/scripts/relocate_to_ssd.sh --samples

# 2. Service user + dirs
sudo useradd -r -G dialout -s /usr/sbin/nologin flightctl || true
sudo install -d -o flightctl -g flightctl /etc/flightctl /opt/flightctl /mnt/ssd/data/fts

# 3. FTS hardcodes /opt/fts at import — point it at the SSD (keeps eMMC free)
sudo ln -sfn /mnt/ssd/data/fts /opt/fts && sudo chown -h flightctl:flightctl /opt/fts

# 4. Put mavp2p on PATH (or point the unit at the SSD copy)
sudo install -m755 /mnt/ssd/flightctl/bin/mavp2p /usr/local/bin/mavp2p

# 5. Install units + config, enable
sudo cp flightctl/systemd/*.service /etc/systemd/system/
sudo cp flightctl/systemd/mavp2p.env.example   /etc/flightctl/mavp2p.env
sudo cp flightctl/systemd/fts.env.example      /etc/flightctl/fts.env
sudo cp flightctl/configs/jetson_gateway.json  /etc/flightctl/
sudo cp flightctl/run_gateway.py               /opt/flightctl/
sudo cp flightctl/udev/99-flightctl-serial.rules.example /etc/udev/rules.d/99-flightctl-serial.rules
sudo udevadm control --reload && sudo udevadm trigger
sudo systemctl daemon-reload && sudo systemctl enable --now mavp2p freetakserver meshsa-gateway

# 6. Betaflight Configurator GUI (PWA): install Chromium, then open https://app.betaflight.com
sudo apt-get install -y chromium-browser
```

## Order of operations
1. **Phase 1** `sudo bash flightctl/scripts/relocate_to_ssd.sh` — frees the 97%-full eMMC. Required before installing anything else.
2. **MAVLink** — install mavp2p, enable `mavp2p.service`; run `sim/mavlink_fake.py` to generate traffic.
3. **FreeTAKServer** — `uv venv --python 3.11 /mnt/ssd/venvs/fts && uv pip install 'FreeTAKServer[ui]'`; enable `freetakserver.service`.
4. **Gateway** — run a meshsa node with `configs/jetson_gateway.json`; drone tracks appear in ATAK.
5. **Betaflight** — install the udev rule (above), tune via Chromium/`https://app.betaflight.com`
   (WebSerial), **Disconnect**, then `FC_MODE=msp flightctl/scripts/start_all.sh start` — the
   `msp_source` transport ingests MSP telemetry headlessly and the FC appears as a CoT track.
   See [Real Betaflight FC over USB](#real-betaflight-fc-over-usb-msp-mode).
