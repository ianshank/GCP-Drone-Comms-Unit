# M2 Transport / Endpoint-Authentication Audit

<!-- markdownlint-disable MD013 MD060 -->

Date: 2026-07-08
Scope: every socket-bound or link-bound surface in `packages/meshsa` and
`packages/jetson_yolo_gcs`, and its actual authentication / encryption posture.
Prerequisite task from [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) Track 0.2 / Track E.3: the
maintainer's M2-gate clearance for Initiative-C commanding requires this enumeration first. This
audit **does not clear the gate** — it supplies the evidence the CHARTER §6 decision needs.

Reading order: [CHARTER.md](CHARTER.md) → [ROADMAP.md](ROADMAP.md) → [NEXTSTEPS.md](NEXTSTEPS.md) →
[IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) → this audit.

## Summary

| Dimension | Result |
| --------- | ------ |
| HTTP control surfaces (LLM, commander, scout, **healthz**) | Share one audited primitive (`netauth.py`); all now **fail closed** on a non-loopback bind without a token |
| Observability `/healthz`+`/metrics` | **Fixed on this branch** — was the one fail-open HTTP surface; now routed through `netauth.validate_bind` + bearer-gated `/metrics` |
| Transport encryption default | **Plaintext everywhere by default**; TAK mutual TLS (`:8089`) is the only wired-in transport encryption (opt-in) |
| Transport-layer auth | Ad hoc / per-protocol; no transport-wide framework |
| Loopback-default binds | All HTTP + UDP-ingest surfaces default to `127.0.0.1`; **exception:** TAK multicast binds all interfaces |
| Overall M2 posture | Encryption + per-endpoint HTTP auth exist and mostly fail closed, but auth is **per-surface, not transport-wide** |

## Is there a transport-wide auth framework?

Partially. There is **one shared HTTP auth primitive**, `meshsa/netauth.py`: `is_loopback`
(`netauth.py:17`), constant-time bearer `authorize` (`netauth.py:22`, `hmac.compare_digest` at
`:37`), and fail-closed `validate_bind` (`netauth.py:40-48`). As of this branch it is reused by
**four** aiohttp surfaces — the LLM server, the commander, the scout station, and now the
`/healthz`+`/metrics` server. Everything else is per-protocol and mostly optional: TAK uses TLS,
Meshtastic relies on an out-of-band device PSK, and MAVLink2 signing is wired only on the commander
leg. There is **no transport-wide endpoint-auth framework**.

## Surface inventory

| # | Surface / module | Direction | Default bind + port | Auth (default?) | Encryption (default) | Fail-closed? |
|---|---|---|---|---|---|---|
| 1 | `TakTcpTransport` — `transports/tak.py:163` | Outbound client | `127.0.0.1`; port `None`→**8087 plaintext** / 8089 TLS | Mutual TLS optional (`tls_client_cert/key`); **off** by default | **Plaintext by default**; TLS opt-in, `tls_verify=True` when on | Fails open (plaintext default) |
| 2 | `TakMulticastTransport` — `transports/tak.py:361` | Bidirectional (UDP multicast) | group `239.2.3.1`, port `6969`; socket binds `("", 6969)` = **all interfaces** (`tak.py:341`) | **None** | **None / plaintext** | Fails open (inherent to multicast CoT) |
| 3 | `Pacer` — `transports/pacing.py:19` | **Not network-facing** (token-bucket timing helper) | n/a | n/a | n/a | n/a |
| 4 | `MeshtasticTransport` — `transports/meshtastic_radio.py:89` | Bidirectional (LoRa serial/TCP/BLE) | `connection="serial"`; no IP bind | **Link PSK claimed but NOT applied in code** — `_default_provisioner` sets only `region`, logs channel/psk/freq as device-provisioned (`meshtastic_radio.py:81-86`) | LoRa PHY only; PSK not enforced here | Fails open |
| 5 | `meshsa-llm` server — `llm/server.py` | Inbound listener | `127.0.0.1:8090` | Bearer `MESHSA_LLM_TOKEN` on `/chat`; default off, loopback; `/`+`/healthz` open | Plaintext HTTP | **Fails closed** (`validate_bind`) |
| 6 | Commander HTTP — `flightctl/run_commander.py`, `command/config.py` | Inbound listener | `127.0.0.1:8095` | Bearer `MESHSA_CMD_TOKEN` on `/command/*`; default off, loopback. **MAVLink2 signing** optional on the autopilot leg (`MESHSA_CMD_SIGNING_KEY_FILE`) | Plaintext HTTP | **Fails closed** (`SystemExit` on bad bind) |
| 7 | `/healthz`+`/metrics` — `health.py`, `config.py:122` | Inbound listener | `127.0.0.1:8088`, `enabled=False` | **NOW** bearer `MESHSA_HEALTH_TOKEN` gating `/metrics`; default off, loopback; `/healthz` open | Plaintext HTTP | **NOW fails closed** (`validate_healthz_bind`, this branch) — *was fail-open* |
| 8 | Nemotron inference — `inference.py` | Outbound client | `base_url` from config; `/chat/completions` | API key `Authorization: Bearer`; call skipped if no key | Depends on `base_url` scheme (https expected) | n/a (outbound) |
| 9 | Scout station — `scout/station/app.py`, `config.py:162` | Inbound listener | `127.0.0.1:8099`, token `""` | Bearer on data/mutation routes; default off, loopback; `/healthz` open. **XSS-hardened** (`_html.py` JSON-encoded token, `textContent`, no `innerHTML`) | Plaintext HTTP | **Fails closed** (`validate_bind`) |
| 10 | `DetectionIngestTransport` UDP — `transports/detection_ingest.py:44` | Inbound listener (UDP) | `127.0.0.1:8099` | **None** (any local process may inject) | None / plaintext | Loopback-default; **no bind guard** (fails open on override) |
| 11 | `MavlinkSourceTransport` — `transports/mavlink_source.py` | Inbound (receive-only) | `udpin:127.0.0.1:14550` | **None** (no MAVLink2 signing on ingest) | Plaintext | Loopback-default; fails open on override |
| 12 | `MspSourceTransport` — `transports/msp_source.py` | Inbound (serial poll) | `/dev/ttyACM0` — serial, no network bind | None (physical) | n/a | n/a |
| 13 | `CrsfSourceTransport` — `transports/crsf_source.py` | Inbound (serial poll) | pyserial — serial, no network bind | None (physical) | n/a | n/a |
| 14 | Jetson GStreamer egress — `streaming/gstreamer.py`, `core/config.py:65` | Outbound (RTP/UDP) | `127.0.0.1:5600`, `enabled=True` | **None** (RTP has no auth) | None / plaintext RTP/H.264 | Fails open (unauth video egress, on by default) |
| 15 | Jetson `LandingTargetBridge` — `mavlink/bridge.py`, `core/config.py:75` | Bidirectional MAVLink | `udpout:127.0.0.1:14550` | **None** (no signing on this leg) | Plaintext UDP | Feature off by default; when on, **safety** fail-closed via heartbeat gate (not an auth control) |
| 16 | Jetson health listener | — | **Does not exist** (only the gstreamer udpsink; `--health-check` is a CLI self-test) | n/a | n/a | n/a |

## Gap summary

- **`/healthz`+`/metrics` was the one fail-open HTTP surface — fixed on this branch.** Every other
  HTTP surface routed through `netauth.validate_bind`; `serve_healthz` did not, and its host is
  operator-overridable off-loopback (`MESHSA_HEALTH_HOST`), exposing `/metrics` (router/transport/
  inference counters) unauthenticated. This branch adds `HealthConfig.token` /
  `MESHSA_HEALTH_TOKEN`, a `validate_healthz_bind` guard (refuses a non-loopback bind without a
  token — validated *before* `node.start()` in `cli.py` so a misconfig fails fast without leaking a
  started node), and a bearer gate on `/metrics`. Default (loopback, `token=None`) is unchanged.
- **TAK UDP multicast** binds `("", 6969)` on all interfaces with no auth/encryption
  (`tak.py:341,361-368`). Inherent to multicast CoT, but it is an unauthenticated inbound datagram
  surface reachable on every interface by default.
- **Plaintext by default everywhere.** All HTTP surfaces run `web.run_app`/`TCPSite` with no TLS;
  TAK TCP defaults to plaintext `:8087`; MAVLink, detection UDP, and RTP video are cleartext.
  Confidentiality depends entirely on operators enabling TAK TLS or a trusted/link-encrypted network.
- **Meshtastic "link-layer PSK" is aspirational in code.** `_default_provisioner` applies only the
  LoRa `region` and logs channel/PSK/frequency as "device-provisioned; verify on hardware" without
  setting them (`meshtastic_radio.py:81-86`). The mesh PSK must be pre-provisioned out-of-band.
- **Telemetry-ingest transports trust their source.** `mavlink_source` (`udpin:14550`),
  `detection_ingest` (UDP 8099), and the serial MSP/CRSF sources perform no authentication on
  inbound frames. Loopback / physical-serial defaults are the mitigation, but none carry a
  `validate_bind`-style guard, so a non-loopback override fails open.
- **Shared default port number 8099.** `detection_ingest` (UDP, `detection_ingest.py:49`) and the
  scout station (TCP, `config.py:163`) both default to `8099`. Different protocols → not an OS-level
  collision, but a confusing default worth deconflicting.

## What is done well

- One audited primitive (`netauth.py`) with constant-time bearer comparison (`:37`) and consistent
  fail-closed bind validation, now shared by all four HTTP surfaces.
- The commander adds MAVLink2 signing on the autopilot leg and a fail-closed pre-arm heartbeat gate
  (`command/health.py`).
- The scout station is deliberately XSS-hardened (JSON-encoded token injection, `textContent`/DOM
  rendering, never `innerHTML`).
- The commander and the Jetson `LANDING_TARGET` publisher fail **closed on safety** — arm/publish
  are suppressed without a fresh autopilot HEARTBEAT (`bridge.py`, `command/health.py`).

## Verdict for the maintainer (CHARTER §6 M2 gate)

M2's transport-encryption building block (TAK mutual TLS) exists, and per-endpoint HTTP auth now
exists and **fails closed on all four HTTP surfaces**. But this is **per-surface** auth, **not
transport-wide endpoint authentication**: the wire transports (Meshtastic, MAVLink/MSP/CRSF ingest,
detection UDP, TAK multicast, Jetson RTP/MAVLink) carry no endpoint auth, and encryption is
plaintext-by-default outside opt-in TAK TLS. The CHARTER §3 commanding carve-out requires that "no
command surface ships before M2 transport auth/TLS lands." The commander HTTP surface itself is
loopback-default, token-gated, fail-closed, and MAVLink2-signable — but the broader "M2 transport
auth" precondition is **not** met transport-wide. **Recommendation:** keep the commanding M2 gate
**closed** pending a deliberate maintainer decision on whether per-surface auth + opt-in TLS
satisfies §3, or whether transport-wide auth is required first.

## Follow-up backlog (deferred — see [NEXTSTEPS.md](NEXTSTEPS.md))

1. Fail-closed bind guard for `detection_ingest` / `mavlink_source` on a non-loopback `host`/`endpoint`.
2. Implement Meshtastic PSK provisioning, or downgrade the docs/config so operators don't assume an
   enforced PSK.
3. Deconflict the shared `8099` default between `detection_ingest` and the scout station.
4. Document that all HTTP + MAVLink/RTP surfaces are plaintext by default; TAK TLS (`:8089`) is the
   only wired-in transport encryption.
