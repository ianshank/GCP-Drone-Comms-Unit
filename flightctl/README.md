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
| `scripts/relocate_to_ssd.sh` | **Phase 1** — conservative eMMC→SSD relocation (Docker data-root, caches, mount hardening, cleanup). **Run with sudo after reviewing.** |
| `configs/jetson_gateway.json` | Example meshsa node: `mavlink_source`(telemetry) → `tak_tcp`(cot, air type). |
| `sim/mavlink_fake.py` | pymavlink `udpout` simulator — emits HEARTBEAT + GLOBAL_POSITION_INT for dev/e2e (no autopilot needed). |
| `systemd/mavp2p.service` + `mavp2p.env.example` | MAVLink proxy (mavp2p) unit. |
| `systemd/freetakserver.service` + `fts.env.example` | FreeTAKServer unit (Python 3.11 venv). |
| `udev/99-flightctl-serial.rules.example` | Stable `/dev/flightctl-*` serial symlinks for autopilot/FC. |

## Quick local test (no hardware, no services) — works today
```bash
# the meshsa SSD venv already has pymavlink? if not: uv pip install pymavlink (after Phase 1)
cd packages/meshsa && /mnt/ssd/venvs/meshsa/bin/python -m pytest -q   # 155 tests, 100% cov
```

## Order of operations
1. **Phase 1** `sudo bash flightctl/scripts/relocate_to_ssd.sh` — frees the 97%-full eMMC. Required before installing anything else.
2. **MAVLink** — install mavp2p, enable `mavp2p.service`; run `sim/mavlink_fake.py` to generate traffic.
3. **FreeTAKServer** — `uv venv --python 3.11 /mnt/ssd/venvs/fts && uv pip install 'FreeTAKServer[ui]'`; enable `freetakserver.service`.
4. **Gateway** — run a meshsa node with `configs/jetson_gateway.json`; drone tracks appear in ATAK.
5. **Betaflight** — install Chromium, open `https://app.betaflight.com` (WebSerial) for tuning; the `msp_source` transport (Phase 5) ingests MSP telemetry headlessly.
