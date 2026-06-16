# Next Steps — GCP-Drone-Comms-Unit

> Changeable, near-term backlog. The stable plan is [CHARTER.md](CHARTER.md) (scope +
> invariants) and [ROADMAP.md](ROADMAP.md) (milestone trajectory); keep this aligned with
> both. Update freely as work lands.

## Done (this initial PR)
- `telemetry` codec + `mavlink_source` (pymavlink) + `msp_source` (Betaflight MSP/YAMSPy)
  transports; drone/FC fixes → **air** CoT tracks with no schema bump.
- Config-driven gateway (`flightctl/run_gateway.py` + `configs/jetson_gateway.json`),
  MAVLink simulator, systemd units, FTS setup, SSD-relocation tooling.
- `--log-level` / `MESHSA_LOG_LEVEL`; 165 tests at 100% line+branch; mypy `--strict` + ruff clean.
- Manually verified on-device: fake MAVLink → gateway → live FreeTAKServer `:8087` → ATAK
  viewer received the air track.

## GCS commanding (initiative — **CHARTER carve-out ratified 2026-06-16**)
> Two-way vehicle commanding is now an authorized but **bounded** scope per the
> [CHARTER.md](CHARTER.md) §3 supervised-commanding carve-out (ratified 2026-06-16). The
> MAVLink plumbing is the easy part; the work is the safety/auth/audit layer. Sequence this
> **after** M2 hardening — do not ship a command surface before TLS + auth land.
- [x] **Scope ratified** in CHARTER.md (2026-06-16): whitelist safe commands first
      (SET_MODE, RTL) before destructive ones (force-disarm). Maintainer sign-off recorded.
- [ ] **Command path via the registry:** add a write-capable `mavlink_sink`
      transport + command codec (no router/node edits). Reuse `mavlink2rest` (`:8088`)
      or pymavlink. Prefer `COMMAND_INT` for positional commands; confirm via
      `COMMAND_ACK`/`MAV_RESULT` with bounded retries on missing ACK.
      ([command](https://mavlink.io/en/services/command.html) /
      [mission](https://mavlink.io/en/services/mission.html) specs)
- [ ] **Safety layer (the real work):** operator-confirmation gate, command
      authentication, full audit log, and `health_all_ok`-style preconditions before
      arm. Note `MAV_CMD_COMPONENT_ARM_DISARM` param2=`21196` **force-bypasses
      interlocks incl. in-flight disarm** — gate it explicitly.
      ([ArduPilot](https://ardupilot.org/dev/docs/mavlink-arming-and-disarming.html))
- [ ] ⚠️ `mavlink2rest` on `:8088` is a bidirectional command surface with **no
      built-in auth or interlock** ([mavlink2rest](https://github.com/mavlink/mavlink2rest));
      MAVSDK acks signal *intent, not completion*
      ([MAVSDK](https://mavsdk.mavlink.io/main/en/cpp/guide/taking_off_landing.html)).
- [ ] Keep `meshsa.llm` **read-only by default**; any future command tool must be
      gated behind explicit human confirmation, never autonomous model issuance.

## Near-term (M2 hardening)
- [ ] **Automated FTS e2e** (non-coverage job): bring up FTS in CI on a self-hosted Jetson
      runner; assert a track via the FTS REST API and a multicast CoT listener.
- [ ] **TLS CoT (`:8089`)** for `TakTcpTransport` (currently plaintext) + signed ATAK
      data-package / cert generation flow; document the client import. Keep plain `:8087`
      for closed dev nets. Follow PyTAK conventions: `tls://` scheme + `PYTAK_TLS_CLIENT_CERT`
      ([PyTAK config](https://pytak.readthedocs.io/en/stable/configuration/)); generate the
      FTS CA→server→per-user PKI with an `AtakOfTheCerts`-style helper
      ([ATAK-Certs](https://github.com/lennisthemenace/ATAK-Certs)).
- [ ] **Pacing / rate-limit** to FTS (PyTAK-style **`FTS_COMPAT=1`**) so fast tracks aren't
      dropped ([PyTAK](https://github.com/snstac/pytak)).
- [ ] **Transport observability:** periodic rx-count / link-state structlog fields on
      `mavlink_source` / `msp_source`; surface `dropped_inbox_full` per transport; export
      `RouterMetrics` (Prometheus/JSON). Add a **Grafana dashboard** mapping the existing
      `rx/tx/forwarded/dropped/reconnects` counters to the four golden signals
      ([Google SRE](https://sre.google/sre-book/monitoring-distributed-systems/)). If the
      gateway is ever run multi-process, set & **wipe `PROMETHEUS_MULTIPROC_DIR` between runs**
      ([client_python](http://prometheus.github.io/client_python/multiprocess/)).
- [x] **Pin FTS deps** in a constraints file (`flightctl/constraints/fts-constraints.txt`:
      `setuptools<81`, `requests`, `opentelemetry==1.20.0`) so `setup_fts.sh` is reproducible.

## Mid-term (M3 richer tracks)
- [ ] Course/speed/battery/attitude as **additive `payload` keys** + a CoT detail-aware
      codec (no `MessageKind` change; bump `schema_version` only if the envelope shape changes).
- [ ] Sensor Point-of-Interest / field-of-view CoT; multiple simultaneous UAS with stable UIDs.
      Implement SPI/FOV **natively in the `cot` codec** — do not depend on FreeTAKUAS
      ([abandoned since 2022](https://github.com/FreeTAKTeam/FreeTAKUAS)).
- [ ] Betaflight ≥2025.12 MAVLink-on-UART path (reuse `mavlink_source`); MSP attitude/altitude.
      Note Betaflight 2025.12+ also speaks **MAVLink over the ExpressLRS link**
      ([Betaflight wiki](https://betaflight.com/docs/wiki/guides/current/MAVLinkELRS) /
      [ExpressLRS](https://www.expresslrs.org/software/mavlink/)) — consolidating on
      MAVLink-over-ELRS could retire the bespoke CRSF GPS decode. Track [mLRS](https://github.com/olliw42/mLRS).
- [ ] Optional **Remote ID → CoT** ingest via a `DroneCOT`-style transport
      ([DroneCOT](https://github.com/snstac/dronecot)) for ODID/DJI DroneID situational awareness.

## FPV ground-side subsystem (`meshsa.fpv`)
Implemented greenfield (Phase 0 Errata E1 + Phase 1 Spec v1.1); see
[docs/specs/](specs/) and the ARCHITECTURE section. Status:
- [x] CRSF parsers, CRC framing, echo-suppressed `CrsfLink`, address prober (E1.2/E1.3).
- [x] Telemetry store + co-signal link-health monitor (hysteresis, version-keyed floors).
- [x] Flight logger (writer thread, drop-and-count, versioned manifest + JSONL headers).
- [x] `ArmGuard` pre-flight interlock + CHARTER §3 carve-out.
- [x] `fpv-telemetry-monitor` / `fpv-log-replay` / `fpv-log-convert`; 100% module coverage.
- [x] **Human sign-off on the CHARTER §3 carve-out** (RC-TX scope expansion) — ratified 2026-06-12.
- [ ] Bench validation (§8): live LinkStats on hardware, voltage calibration, ratio sweep,
      antenna-removal transitions, `!FS!` end-to-end — thresholds remain provisional until then.
- [ ] Phase 2: wire the camera into the existing `frames.jsonl`/`video` stub (no schema bump).
- [x] Additive `crsf_source` transport so CRSF telemetry becomes an ATAK air track (0.3.0;
      decodes GPS 0x02 → `GpsSensor` → `telemetry` codec; `DATASET_SCHEMA` 1 → 2).

## Ops / packaging (M4–M5)
- [ ] systemd enablement with a dedicated `flightctl` service user + correct ownership of the
      SSD venvs (currently proven via manual run).
- [ ] Betaflight Configurator: confirm Chromium PWA path on the unit; document source build.
- [ ] Optional **root-on-NVMe** appliance build to remove the eMMC constraint entirely.
- [ ] Reproducible multi-arch image; signed releases; GHCR publish on tags (workflow exists).
- [ ] Fleet resilience: **Meshtastic store-and-forward** for intermittent links
      ([S&F module](https://meshtastic.org/docs/configuration/module/store-and-forward-module/)).

## Code-quality backlog (2026-06-16 gap scan)
Found by a read-only gap/deviation scan of the 0.3.x hardening + FPV-Phase-2 work; lint,
`mypy --strict`, format, and the test suite are all green — these are design/robustness items.
- [ ] **[security] `meshsa.llm` server binds `0.0.0.0` with no auth** (`llm/server.py`
      `DEFAULT_HOST`; mirrored in `flightctl/llm/README.md`). The `/chat` endpoint spends
      Anthropic tokens and discloses live drone/track positions. Default to `127.0.0.1` + add a
      `MESHSA_LLM_TOKEN` bearer check. **M2 hardening prerequisite — gates the commanding
      initiative** (see [ROADMAP.md](ROADMAP.md) Initiative C).
- [ ] **[robustness] `TakMulticastTransport._recv_loop` has no error recovery** (`transports/tak.py`),
      unlike the TCP supervisor — a transient socket error silently and permanently stops
      multicast ingestion. Wrap in `try/except` + WARNING + rebuild.
- [ ] **[safety] `ArmGuard._last_report` is read/written across methods without a lock**
      (`fpv/arm_guard.py`); `_emit_blocked` re-reads it and can mismatch. Add a `Lock` or
      document/enforce the single-thread contract.
- [ ] **[consistency] `FlightLogger.dropped_records` omits the `"frames"` key**
      (`fpv/flight_logger.py`) so the manifest never reports `frames: 0`; init all three streams.
- [ ] **[robustness] guard unguarded teardown/parse paths:** `camera.py close()` source close,
      `fpv/tools/replay.py` `rec[...]` KeyErrors, `mavlink_source` attribute assumptions; and
      throttle the per-frame WARNING floods in `crsf_source` / `meshtastic_radio`.
- [ ] **[cleanup] drop `# pragma: no cover` on pure logic** in `fpv/crsf/rc.py` (span==0 guards)
      and source the remaining magic numbers (`rc.py` pad=992, `monitor.py` interval) from config.

## Known risks / watch-items
- FreeTAKServer dependency conflicts on aarch64 (opentelemetry/greenlet/eventlet) — pinned
  for now; re-verify on FTS upgrades.
- arm64 `npm install` for the Configurator source build is untested upstream — prefer the PWA.
- Jetson eMMC is space-constrained; caches/Docker/venvs and `/usr/local/cuda`+`/opt` are
  relocated to the NVMe SSD (see `flightctl/scripts/`).
- **Insecure-by-default building blocks:** mavlink2rest, FreeTAKServer, and the TAK
  transports are all unauthenticated/plaintext out of the box — any commanding or field
  deployment must add the auth/TLS/confirmation layer first.
- **Moving targets:** pin versions for `mavlink2rest`, PyTAK, and Betaflight — all change fast.
- **Unverified (needs focused follow-up research):** MAVLink 2 message signing, multi-GCS
  link arbitration, arm64 signed-image + systemd-hardening specifics, and Meshtastic
  store-and-forward semantics were flagged but not confirmed in the 2026-06 research pass.
