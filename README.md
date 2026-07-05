# GCP-Drone-Comms-Unit

A field comms unit that bridges **drone / flight-controller telemetry** and a **mesh
situational-awareness (SA) network** into **TAK / ATAK**. It runs on an NVIDIA Jetson
(or a Pi) and turns MAVLink autopilots, Betaflight flight controllers, and LoRa/HaLow/IP
mesh nodes into **Cursor-on-Target (CoT)** tracks that ATAK clients on phones can see in
real time.

> The importable Python framework is published as the **`meshsa`** package (mesh
> situational awareness). This repository, **GCP-Drone-Comms-Unit**, is the framework
> plus the deployment/ops layer (`flightctl/`) that wires it into a real comms unit.
> Despite the name, **"GCP" here is not Google Cloud Platform** — there is no cloud
> backend or GCP dependency; everything (including the TAK server) is self-hosted on
> the edge device.

## What it does
- **Telemetry → CoT:** a MAVLink autopilot (`mavlink_source`), a Betaflight FC over MSP
  (`msp_source`), or an FPV CRSF/ELRS feed (`crsf_source`) becomes an **air** track in ATAK,
  with no core changes — telemetry sources self-register as transports and bridge through the
  existing `cot` codec.
- **Mesh SA bridge:** LoRa (Meshtastic), HaLow 802.11s, and IP mesh exchange versioned
  position/chat envelopes; one node bridges the mesh to a TAK server (FreeTAKServer) and/or
  the ATAK multicast SA group.
- **FPV link health & flight logging (`meshsa.fpv`):** ingests **CRSF** telemetry from an
  ELRS handset module over half-duplex UART, evaluates link health (LQ/RSSI/staleness),
  logs synchronized RC + telemetry + event sessions to a versioned JSONL dataset, and
  enforces a **pre-flight** arm interlock. Console tools: `fpv-telemetry-monitor`,
  `fpv-log-replay`, `fpv-log-convert`. Install with the `fpv` extra:
  `pip install -e "packages/meshsa[fpv]"`. (Pre-flight arm-gating is a deliberate, bounded
  exception to the read-only charter — see [docs/CHARTER.md](docs/CHARTER.md) §3.)
- **Observability & a read-only SA assistant:** opt-in `/healthz` + `/metrics`
  (Prometheus/JSON) on the gateway; an optional, **read-only** `meshsa.llm` assistant answers
  operator questions over live telemetry and TAK tracks (it issues no vehicle commands).
- **AI-powered mesh inference (`meshsa.inference`):** an optional **NVIDIA Nemotron NIM**
  bridge subscribes to mesh traffic, runs tactical AI analysis, and broadcasts
  AI insight summaries (configurable prefix via `MESHSA_INFERENCE_INSIGHT_PREFIX`).
  Install with `pip install meshsa[inference]`; configure via `MESHSA_INFERENCE_*`
  environment variables (12 fields incl. backoff tuning). Thread-safe, feedback-loop
  safe (insight messages are never re-analyzed), with configurable retry backoff.
- **Vineyard structural-anomaly scouting (`meshsa.scout`):** an offline, **hardware-free**
  pipeline that turns a mapping survey (RGB detections + autopilot pose) into a georeferenced,
  deduplicated **anomaly map** — rendered on the existing TAK/CoT field map and an optional thin
  `aiohttp`+MapLibre operator view. Reuses `cv.geo` georeferencing and the detection→MARKER→CoT
  path; adds DEM-terrain projection, pose/AGL fusion, and offline survey/mission export
  (QGC `.plan` / ArduPilot `.waypoints` for a human to load, under a CHARTER §3 carve-out —
  no autonomy). `meshsa-scout` CLI (`replay`/`gen-mission`/`run-station`/`--health-check`);
  install `pip install "meshsa[scout]"`; config via `MESHSA_SCOUT_*`.
- **Modular & backward-compatible by construction:** new transports/codecs register via an
  open/closed registry; every wire envelope is `schema_version`-gated; a node tolerates
  configs written for newer/older builds.

## Layout

| Path | What lives here |
| ---- | --------------- |
| [packages/meshsa](packages/meshsa) | `meshsa` Python framework (registry-based codecs + transports, src layout; includes `meshsa.scout` vineyard scouting) |
| [flightctl](flightctl) | Flight-control + TAK **ops layer**: gateway config, systemd units, SSD/relocation + FTS setup scripts, MAVLink simulator, udev |
| [ops/pi5-node](ops/pi5-node) | Raspberry Pi 5 user-node provisioning (`mesh-up.sh`, `setup_pi5_node.sh`) |
| [ops/base-service](ops/base-service) | Base-node systemd service unit + install guide |
| [hardware](hardware) | 3D-printable enclosures (GCS, user nodes, Jetson case) |
| [docs](docs) | [Charter](docs/CHARTER.md) (stable north-star), [Roadmap](docs/ROADMAP.md) (milestone trajectory), [C4](docs/C4.md), [Architecture](docs/ARCHITECTURE.md), [Next steps](docs/NEXTSTEPS.md), [Audit](docs/AUDIT_REPORT.md) |
| [tools](tools) | `Dockerfile`, `Makefile` |
| [AGENTS.md](AGENTS.md) | Canonical AI agent operating guide |
| [.github/workflows](.github/workflows) | CI + release pipelines |

## Quick start (development)

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e "packages/meshsa[dev]"
cd packages/meshsa && pytest          # full suite, ≥90% coverage gate (900+ tests, ~99%)
```

Drone/FC telemetry → CoT (no hardware needed — uses the bundled simulator):

```bash
pip install -e "packages/meshsa[mavlink]"
python flightctl/sim/mavlink_fake.py &                 # emit fake MAVLink on udp:14550
python flightctl/run_gateway.py --config flightctl/configs/jetson_gateway.json
```

Real Meshtastic ↔ FreeTAKServer bridge:

```bash
pip install -e "packages/meshsa[meshtastic]"
meshsa-base --port /dev/ttyUSB0 --fts-host 127.0.0.1 --lat 37.0 --lon -122.0 --callsign BASE1
```

## Deployment
- **Flight-control + TAK edge node:** [flightctl/README.md](flightctl/README.md) (Jetson SSD
  relocation, FreeTAKServer setup, mavp2p, the gateway service).
- **Base node** (Meshtastic ↔ TAK bridge): [ops/base-service/INSTALL_base_node.md](ops/base-service/INSTALL_base_node.md).
- **Pi 5 user node** (HaLow mesh + ADS-B): [ops/pi5-node/README_pi5_node.md](ops/pi5-node/README_pi5_node.md).

## For contributors and AI agents
Start with [docs/CHARTER.md](docs/CHARTER.md) (stable scope + invariants) and
[docs/ROADMAP.md](docs/ROADMAP.md) (stable milestone trajectory) — neither changes per task —
then [AGENTS.md](AGENTS.md). See [CONTRIBUTING.md](CONTRIBUTING.md),
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md); security disclosures via [SECURITY.md](SECURITY.md).

## License
[Apache-2.0](LICENSE).
