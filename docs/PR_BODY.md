# Initial contribution — drone/FC telemetry → CoT/TAK on a mesh-SA framework

Initial PR for **GCP-Drone-Comms-Unit**: the `meshsa` framework plus the `flightctl`
ops layer that turns a Jetson/Pi into a field comms unit bridging **drone & flight-controller
telemetry** and a **mesh SA network** into **TAK/ATAK** as Cursor-on-Target tracks.

## What's included
- **Framework (`packages/meshsa`)** — registry-based transports + codecs, a versioned
  `Envelope`, an async router/bridge with per-transport codec selection and msg-id dedupe.
- **Flight-control telemetry (new):**
  - `telemetry` codec — stateless structured-frame ↔ `PLI` `Envelope` map.
  - `mavlink_source` (pymavlink) and `msp_source` (Betaflight MSP/YAMSPy) — receive-only
    source transports; the stateful parse runs in a reader thread, injectable for tests.
  - Drones render as **air** CoT tracks via per-transport `cot` `codec_options` —
    **no `MessageKind` change, no `schema_version` bump**; omit the sources and it's the
    prior mesh node byte-for-byte.
- **`flightctl/` ops layer** — config-driven gateway (`run_gateway.py` +
  `configs/jetson_gateway.json`), MAVLink simulator, systemd units (mavp2p / FreeTAKServer /
  gateway), FTS setup + SSD-relocation scripts, udev rule.
- **Stack orchestration + browser UIs (new):** `scripts/start_all.sh`
  (`start`/`stop`/`status`/`restart`) brings the whole node up in dependency order with a
  readiness wait per service; `configs/jetson_gateway.proxy.json` runs the gateway behind the
  mavp2p proxy (`udpin:…:14551`). Browser UIs: FreeTAKServer Web UI (`:5000`), the FreeTAKHub
  **WebMap** Node-RED flow (`:1880/tak-map/`), and **mavlink2rest** (`:8088`) as the
  in-browser MAVLink GCS. Two non-obvious wiring constraints are encoded in the script and
  documented in `flightctl/README.md`: mavp2p `udpc` consumers must bind *before* mavp2p
  starts, and mavlink2rest only ingests MAVLink **v2** (sim runs `MAVLINK20=1`).
- **Docs** — `docs/CHARTER.md` (stable north-star), `docs/C4.md` (C4 + data-flow),
  `docs/NEXTSTEPS.md`, updated README/AGENTS.

## Quality
- **165 tests, 100% line+branch coverage**; `mypy --strict` clean; `ruff` + `ruff format` clean;
  wheel + sdist build (`0.2.0`).
- Hardware/socket glue is the only `# pragma: no cover`; unit/integration tests use fakes
  (no radios, sockets, or live servers). Config-driven bridge e2e asserts MAVLink-fix → CoT-air.
- **Full stack verified on-device** (Jetson Orin Nano, JetPack 6.2) via `start_all.sh`:
  ordered bring-up of all seven services, all ports healthy, live MAVLink → mavlink2rest
  REST, and simulated MAVLink → gateway → FreeTAKServer `:8087` → relayed CoT (`uav-1`) to a
  TCP client (the ATAK path) and the WebMap.
- **Manually verified on-device** (Jetson Orin Nano, JetPack 6.2): simulated MAVLink →
  gateway → live FreeTAKServer `:8087` → ATAK-style viewer received the air track.
  (The automated suite asserts the bridge via loopback, not against a live FTS.)

## Backward compatibility & invariants
Open/closed registry (no core edits for new mediums), `schema_version`-gated wire,
DI via `Protocol`, config-driven (no magic numbers) — see `docs/CHARTER.md` §4.

## Notes for reviewers
- `flightctl/` is a deployment/runbook layer; scripts carry machine paths framed as
  edit-before-running, and the SSD-relocation script documents the NVIDIA-meta autoremove
  cascade hazard it now avoids.
- Follow-ups (TLS CoT, FTS rate-limit pacing, richer CoT detail, automated FTS e2e on a
  self-hosted runner) are tracked in `docs/NEXTSTEPS.md`.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
