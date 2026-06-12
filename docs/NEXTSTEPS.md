# Next Steps — GCP-Drone-Comms-Unit

> Changeable, near-term backlog. The stable long-term plan is [CHARTER.md](CHARTER.md);
> keep this aligned with it. Update freely as work lands.

## Done (this initial PR)
- `telemetry` codec + `mavlink_source` (pymavlink) + `msp_source` (Betaflight MSP/YAMSPy)
  transports; drone/FC fixes → **air** CoT tracks with no schema bump.
- Config-driven gateway (`flightctl/run_gateway.py` + `configs/jetson_gateway.json`),
  MAVLink simulator, systemd units, FTS setup, SSD-relocation tooling.
- `--log-level` / `MESHSA_LOG_LEVEL`; 165 tests at 100% line+branch; mypy `--strict` + ruff clean.
- Manually verified on-device: fake MAVLink → gateway → live FreeTAKServer `:8087` → ATAK
  viewer received the air track.

## Near-term (M2 hardening)
- [ ] **Automated FTS e2e** (non-coverage job): bring up FTS in CI on a self-hosted Jetson
      runner; assert a track via the FTS REST API and a multicast CoT listener.
- [ ] **TLS CoT (`:8089`)** + signed ATAK data-package / cert generation flow; document the
      client import. Keep plain `:8087` for closed dev nets.
- [ ] **Pacing / rate-limit** to FTS (PyTAK-style `FTS_COMPAT`) so fast tracks aren't dropped.
- [ ] **Transport observability:** periodic rx-count / link-state structlog fields on
      `mavlink_source` / `msp_source`; surface `dropped_inbox_full` per transport; export
      `RouterMetrics` (Prometheus/JSON).
- [ ] **Pin FTS deps** in a constraints file (`setuptools<81`, `requests`,
      `opentelemetry==1.20.0`) so `setup_fts.sh` is reproducible across machines.

## Mid-term (M3 richer tracks)
- [ ] Course/speed/battery/attitude as **additive `payload` keys** + a CoT detail-aware
      codec (no `MessageKind` change; bump `schema_version` only if the envelope shape changes).
- [ ] Sensor Point-of-Interest / field-of-view CoT; multiple simultaneous UAS with stable UIDs.
- [ ] Betaflight ≥2025.12 MAVLink-on-UART path (reuse `mavlink_source`); MSP attitude/altitude.

## FPV ground-side subsystem (`meshsa.fpv`)
Implemented greenfield (Phase 0 Errata E1 + Phase 1 Spec v1.1); see
[docs/specs/](specs/) and the ARCHITECTURE section. Status:
- [x] CRSF parsers, CRC framing, echo-suppressed `CrsfLink`, address prober (E1.2/E1.3).
- [x] Telemetry store + co-signal link-health monitor (hysteresis, version-keyed floors).
- [x] Flight logger (writer thread, drop-and-count, versioned manifest + JSONL headers).
- [x] `ArmGuard` pre-flight interlock + CHARTER §3 carve-out.
- [x] `fpv-telemetry-monitor` / `fpv-log-replay` / `fpv-log-convert`; 100% module coverage.
- [ ] **Human sign-off on the CHARTER §3 carve-out** (RC-TX scope expansion).
- [ ] Bench validation (§8): live LinkStats on hardware, voltage calibration, ratio sweep,
      antenna-removal transitions, `!FS!` end-to-end — thresholds remain provisional until then.
- [ ] Phase 2: wire the camera into the existing `frames.jsonl`/`video` stub (no schema bump).
- [ ] Optional additive `crsf_source` transport so CRSF telemetry becomes an ATAK air track.

## Ops / packaging (M4–M5)
- [ ] systemd enablement with a dedicated `flightctl` service user + correct ownership of the
      SSD venvs (currently proven via manual run).
- [ ] Betaflight Configurator: confirm Chromium PWA path on the unit; document source build.
- [ ] Optional **root-on-NVMe** appliance build to remove the eMMC constraint entirely.
- [ ] Reproducible multi-arch image; signed releases; GHCR publish on tags (workflow exists).

## Known risks / watch-items
- FreeTAKServer dependency conflicts on aarch64 (opentelemetry/greenlet/eventlet) — pinned
  for now; re-verify on FTS upgrades.
- arm64 `npm install` for the Configurator source build is untested upstream — prefer the PWA.
- Jetson eMMC is space-constrained; caches/Docker/venvs and `/usr/local/cuda`+`/opt` are
  relocated to the NVMe SSD (see `flightctl/scripts/`).
