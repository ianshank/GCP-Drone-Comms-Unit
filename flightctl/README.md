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
| `configs/jetson_gateway.proxy.json` | Same node behind the mavp2p proxy: MAVLink in on `udpin:127.0.0.1:14551` (mavp2p fans the autopilot stream to the gateway, mavlink2rest, and any GCS). Used by `start_all.sh`. |
| `sim/mavlink_fake.py` | pymavlink `udpout` simulator — emits HEARTBEAT + GLOBAL_POSITION_INT for dev/e2e (no autopilot needed). |
| `systemd/mavp2p.service` + `mavp2p.env.example` | MAVLink proxy (mavp2p) unit. |
| `systemd/freetakserver.service` + `fts.env.example` | FreeTAKServer unit (Python 3.11 venv). |
| `scripts/setup_fts.sh` | Builds the FTS Python 3.11 venv and installs FreeTAKServer with the verified dep pins via `--constraint`. |
| `constraints/fts-constraints.txt` | Dependency pins (setuptools/opentelemetry/etc.) verified to boot FTS 2.x on this box; consumed by `setup_fts.sh --constraint`. |
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

## Quick local test (no hardware, no services) — works today
```bash
# the meshsa SSD venv already has pymavlink? if not: uv pip install pymavlink (after Phase 1)
cd packages/meshsa && /mnt/ssd/venvs/meshsa/bin/python -m pytest -q   # 165 tests, 100% cov
```

## What is already done vs. what needs root

**Done & verified (no sudo, all on the SSD):** branch + code + 165 tests at 100% cov;
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
5. **Betaflight** — install Chromium, open `https://app.betaflight.com` (WebSerial) for tuning; the `msp_source` transport (Phase 5) ingests MSP telemetry headlessly.
