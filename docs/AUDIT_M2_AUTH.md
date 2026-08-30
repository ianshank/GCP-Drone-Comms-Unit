# M2 Transport / Endpoint-Authentication Audit

<!-- markdownlint-disable MD013 MD060 -->

Date: 2026-07-08; surface inventory re-derived and corrected 2026-07-31 (see
[CHARTER_ALIGNMENT_AUDIT_PLAN.md](CHARTER_ALIGNMENT_AUDIT_PLAN.md) Phase D — this file's rows #10/#11
and two Gap-summary items were stale against commit `fab3ab1`, landed 2026-07-29 after the original
audit date).
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
| HTTP control surfaces (LLM, commander, scout, **healthz**, **operator UI**) | Share one audited primitive (`netauth.py`); all now **fail closed** on a non-loopback bind without a token |
| Observability `/healthz`+`/metrics` | **Fixed on this branch** — was the one fail-open HTTP surface; now routed through `netauth.validate_bind` + bearer-gated `/metrics` |
| Transport encryption default | **Plaintext everywhere by default**; TAK mutual TLS (`:8089`) is the only wired-in transport encryption (opt-in) |
| Transport-layer auth | Ad hoc / per-protocol; no transport-wide framework |
| Loopback-default binds | All HTTP + UDP-ingest surfaces default to `127.0.0.1`; **exception:** TAK multicast binds all interfaces |
| Overall M2 posture | Encryption + per-endpoint HTTP auth exist and mostly fail closed, but auth is **per-surface, not transport-wide** |

## Is there a transport-wide auth framework?

Partially. There is **one shared HTTP auth primitive**, `meshsa/netauth.py`:
`netauth.py::is_loopback`, constant-time bearer `netauth.py::authorize` (via
`hmac.compare_digest`), and fail-closed `netauth.py::validate_bind` (citations are
`module::symbol` — file:line refs rotted with every import edit). As of this branch it is reused by
**five** aiohttp surfaces — the LLM server, the commander, the scout station, the
`/healthz`+`/metrics` server, and the operator console (`meshsa.ui`). Everything else is
per-protocol and mostly optional: TAK uses TLS,
Meshtastic relies on an out-of-band device PSK, and MAVLink2 signing is wired only on the commander
leg. There is **no transport-wide endpoint-auth framework**. This branch adds the
`TransportAuthPolicy` seam (`netauth.py`) — a thin protocol the five HTTP surfaces already satisfy
via the default policy — so non-HTTP surfaces (detection UDP, MAVLink ingest) have a defined place
to plug datagram signing later; the seam is **not** an implementation, and the framework gap stands
until one lands.

## Surface inventory

| # | Surface / module | Direction | Default bind + port | Auth (default?) | Encryption (default) | Fail-closed? |
|---|---|---|---|---|---|---|
| 1 | `TakTcpTransport` — `transports/tak.py::TakTcpTransport` | Outbound client | `127.0.0.1` (`defaults.DEFAULT_LOCAL_TARGET_HOST`); port `None`→**8087 plaintext** / 8089 TLS (`defaults.PORT_FTS_TCP`/`PORT_TAK_TLS`) | Mutual TLS optional (`tls_client_cert/key`); **off** by default | **Plaintext by default**; TLS opt-in, `tls_verify=True` when on | Fails open (plaintext default) |
| 2 | `TakMulticastTransport` — `transports/tak_multicast.py::TakMulticastTransport` | Bidirectional (UDP multicast) | group `239.2.3.1`, port `6969` (`defaults.DEFAULT_TAK_MULTICAST_GROUP`/`PORT_TAK_MULTICAST`); socket binds `("", 6969)` = **all interfaces** (`tak_multicast.py::_default_multicast_io`) | **None** | **None / plaintext** | Fails open (inherent to multicast CoT) |
| 3 | `Pacer` — `transports/pacing.py::Pacer` | **Not network-facing** (token-bucket timing helper) | n/a | n/a | n/a | n/a |
| 4 | `MeshtasticTransport` — `transports/meshtastic_radio.py::MeshtasticTransport` | Bidirectional (LoRa serial/TCP/BLE) | `connection="serial"`; no IP bind | **Link PSK claimed but NOT applied in code** — `_default_provisioner` sets only `region`, logs channel/psk/freq as device-provisioned (`meshtastic_radio.py::_default_provisioner`) | LoRa PHY only; PSK not enforced here | Fails open |
| 5 | `meshsa-llm` server — `llm/server.py` | Inbound listener | `127.0.0.1:8090` | Bearer `MESHSA_LLM_TOKEN` on `/chat`; default off, loopback; `/`+`/healthz` open | Plaintext HTTP | **Fails closed** (`validate_bind`) |
| 6 | Commander HTTP — `flightctl/run_commander.py`, `command/config.py` | Inbound listener | `127.0.0.1:8095` | Bearer `MESHSA_CMD_TOKEN` on `/command/*`; default off, loopback. **MAVLink2 signing** optional on the autopilot leg (`MESHSA_CMD_SIGNING_KEY_FILE`) | Plaintext HTTP | **Fails closed** — **NOW** delegates to `netauth.validate_bind` (this branch; its former local guard used `token is None`, so an empty token passed when called directly) |
| 7 | `/healthz`+`/metrics` — `health.py`, `health.py::HealthConfig.port` | Inbound listener | `127.0.0.1:8098` (moved off `8088` in `code-hygiene-modularity` T-1.4 — `8088` is `mavlink2rest`'s own upstream convention), `enabled=False` | **NOW** bearer `MESHSA_HEALTH_TOKEN` gating `/metrics`; default off, loopback; `/healthz` open | Plaintext HTTP | **NOW fails closed** (`validate_healthz_bind`, this branch) — *was fail-open* |
| 8 | Nemotron inference — `inference/client.py::NemotronClient`, `inference/transport.py::AiohttpTransport` | Outbound client | `base_url` from config; `/chat/completions` | API key `Authorization: Bearer`; call skipped if no key | Depends on `base_url` scheme (https expected) | n/a (outbound) |
| 9 | Scout station — `scout/station/app.py`, `config.py` (`ScoutConfig.station_port`) | Inbound listener | `127.0.0.1:8099`, token `""` | Bearer on data/mutation routes; default off, loopback; `/healthz` open. **XSS-hardened** (`_html.py` JSON-encoded token, `textContent`, no `innerHTML`) | Plaintext HTTP | **Fails closed** (`validate_bind`) |
| 10 | `DetectionIngestTransport` UDP — `transports/detection_ingest.py` | Inbound listener (UDP) | `127.0.0.1:8097` (moved off `8099` in commit `fab3ab1`, 2026-07-29, to deconflict with the scout station's default) | **None on datagrams** (any local process may inject); `token` transport option gates the bind | None / plaintext | **Fails closed** (`netauth.validate_bind` at construction) — non-loopback + token binds with a loud unauthenticated-datagram warning |
| 11 | `MavlinkSourceTransport` — `transports/mavlink_source.py` | Inbound (receive-only) | `udpin:127.0.0.1:14550` | **None on frame contents** (no MAVLink2 signing on ingest); bind gated by an optional `token` transport option via `netauth.validate_bind` | Plaintext | **Fails closed** (`netauth.validate_bind` at construction, commit `fab3ab1`, 2026-07-29) — *was fail-open on override before this commit* |
| 12 | `MspSourceTransport` — `transports/msp_source.py` | Inbound (serial poll) | `/dev/ttyACM0` — serial, no network bind | None (physical) | n/a | n/a |
| 13 | `CrsfSourceTransport` — `transports/crsf_source.py` | Inbound (serial poll) | pyserial — serial, no network bind | None (physical) | n/a | n/a |
| 14 | Jetson GStreamer egress — `streaming/gstreamer.py`, `core/config.py` | Outbound (RTP/UDP) | `127.0.0.1:5600`, **`enabled=False`** (this branch) | **None** (RTP has no auth) — control is default-off + `STREAM_ENABLED=true` opt-in | None / plaintext RTP/H.264 | **NOW fails closed** (default-off; single WARNING with destination at activation) — *was on by default* |
| 15 | Jetson `LandingTargetBridge` — `mavlink/bridge.py`, `core/config.py::MavlinkSettings.endpoint` | Bidirectional MAVLink | `udpout:127.0.0.1:14550` | **None** (no signing on this leg) | Plaintext UDP | Feature off by default; when on, **safety** fail-closed via heartbeat gate (not an auth control) |
| 16 | Jetson health listener | — | **Does not exist** (only the gstreamer udpsink; `--health-check` is a CLI self-test) | n/a | n/a | n/a |
| 17 | Operator console — `ui/app.py`, `ui/config.py` | Inbound listener | `127.0.0.1:8100`, `enabled=False` | Bearer `MESHSA_UI_TOKEN` on `/api/*`; `?token=` gate on `/`; default off, loopback; `/healthz` open. Read-only (`GET` + non-command `POST /api/chat`). XSS-hardened (JSON-encoded injection, `textContent`, no `innerHTML`) | Plaintext HTTP | **Fails closed** (`netauth.validate_bind` inside `build_ui_app`) |

## Gap summary

- **Re-derived fail-open surface count (2026-07-31): 3, and only 1 of those is an actual
  `bind_guard`-scoped listener gap.** A naive `grep -ci 'fails open'` over this file returns 6
  (the session-start banner's figure): 3 surface-inventory rows plus 3 Gap-summary prose lines,
  including the quoted grep command itself; after correcting rows #10/#11
  above, the surface-inventory table has 3 rows still saying "fails open": #1 `TakTcpTransport`, #2
  `TakMulticastTransport`, #4 `MeshtasticTransport`. Of those, only **#2** is actually in
  `bind_guard`'s scope (a listener that calls `.bind()`) and is a declared, still-valid governance
  exception (`.claude/governance.yaml::bind_guard.exceptions`, "multicast CoT binds all interfaces —
  inherent to the protocol"). **#1 and #4 are not listeners at all** — #1 is an outbound TLS client
  connection and #4 is serial/BLE or an outbound `TCPInterface` connect — so their "fails open"
  language describes plaintext/PSK-not-enforced *encryption* posture, not a `bind_guard` gap; neither
  is scanned by `bind_guard` by construction. No new bind surface has appeared since 2026-07-08.
- **`/healthz`+`/metrics` was the one fail-open HTTP surface — fixed on this branch.** Every other
  HTTP surface routed through `netauth.validate_bind`; `serve_healthz` did not, and its host is
  operator-overridable off-loopback (`MESHSA_HEALTH_HOST`), exposing `/metrics` (router/transport/
  inference counters) unauthenticated. This branch adds `HealthConfig.token` /
  `MESHSA_HEALTH_TOKEN`, a `validate_healthz_bind` guard (refuses a non-loopback bind without a
  token — validated *before* `node.start()` in `cli.py` so a misconfig fails fast without leaking a
  started node), and a bearer gate on `/metrics`. Default (loopback, `token=None`) is unchanged.
- **TAK UDP multicast** binds `("", 6969)` on all interfaces with no auth/encryption
  (`tak_multicast.py::_default_multicast_io`, `tak_multicast.py::TakMulticastTransport`). Inherent to multicast CoT,
  but it is an unauthenticated inbound datagram surface reachable on every interface by default.
- **Plaintext by default everywhere.** All HTTP surfaces run `web.run_app`/`TCPSite` with no TLS;
  TAK TCP defaults to plaintext `:8087`; MAVLink, detection UDP, and RTP video are cleartext.
  Confidentiality depends entirely on operators enabling TAK TLS or a trusted/link-encrypted network.
- **Meshtastic "link-layer PSK" is aspirational in code.** `_default_provisioner` applies only the
  LoRa `region` and logs channel/PSK/frequency as "device-provisioned; verify on hardware" without
  setting them (`meshtastic_radio.py::_default_provisioner`). The mesh PSK must be pre-provisioned
  out-of-band.
- **Telemetry-ingest transports trust their source (frame contents), but the bind itself is now
  guarded.** `mavlink_source` (`udpin:14550`), `detection_ingest` (UDP `8097`), and the serial
  MSP/CRSF sources perform no authentication on inbound *frame contents*. Loopback / physical-serial
  defaults are the mitigation. As of commit `fab3ab1` (2026-07-29), both `mavlink_source` and
  `detection_ingest` carry `netauth.validate_bind` at construction, so a non-loopback override
  without a token fails closed on both — this closes what was previously the one remaining fail-open
  gap in this bullet (`mavlink_source`, prior to `fab3ab1`).
- ~~**Shared default port number 8099.**~~ **Resolved** (commit `fab3ab1`, 2026-07-29):
  `detection_ingest` moved to `8097`; the scout station keeps `8099`. No longer a shared default.

## What is done well

- One audited primitive (`netauth.py`) with constant-time bearer comparison
  (`netauth.py::authorize`) and consistent fail-closed bind validation, now shared by all five
  HTTP surfaces.
- Service defaults (ports, hosts, queue/backoff, endpoint) are single-sourced in
  `meshsa/defaults.py` as of `code-hygiene-modularity` T-3.5a, with pinned-value tests
  (`tests/test_defaults.py`) asserting every default in this inventory is numerically unchanged
  and `tools/claude_hooks/literal_guard.py` preventing re-typed literals. **No posture change**:
  every row above keeps its bind, auth, and encryption behavior.
- The commander adds MAVLink2 signing on the autopilot leg and a fail-closed pre-arm heartbeat gate
  (`command/health.py`).
- The scout station is deliberately XSS-hardened (JSON-encoded token injection, `textContent`/DOM
  rendering, never `innerHTML`).
- The commander and the Jetson `LANDING_TARGET` publisher fail **closed on safety** — arm/publish
  are suppressed without a fresh autopilot HEARTBEAT (`bridge.py`, `command/health.py`).

## Verdict for the maintainer (CHARTER §6 M2 gate)

M2's transport-encryption building block (TAK mutual TLS) exists, and per-endpoint HTTP auth now
exists and **fails closed on all five HTTP surfaces**. But this is **per-surface** auth, **not
transport-wide endpoint authentication**: the wire transports (Meshtastic, MAVLink/MSP/CRSF ingest,
detection UDP, TAK multicast, Jetson RTP/MAVLink) carry no endpoint auth, and encryption is
plaintext-by-default outside opt-in TAK TLS. The CHARTER §3 commanding carve-out requires that "no
command surface ships before M2 transport auth/TLS lands." The commander HTTP surface itself is
loopback-default, token-gated, fail-closed, and MAVLink2-signable — but the broader "M2 transport
auth" precondition is **not** met transport-wide. **Recommendation:** keep the commanding M2 gate
**closed** pending a deliberate maintainer decision on whether per-surface auth + opt-in TLS
satisfies §3, or whether transport-wide auth is required first.

## Follow-up backlog (deferred — see [NEXTSTEPS.md](NEXTSTEPS.md))

1. ~~Fail-closed bind guard for `mavlink_source` on a non-loopback `endpoint`.~~ **Done** (commit
   `fab3ab1`, 2026-07-29 — `detection_ingest` was already done on the original audit branch).
2. Implement Meshtastic PSK provisioning, or downgrade the docs/config so operators don't assume an
   enforced PSK.
3. ~~Deconflict the shared `8099` default between `detection_ingest` and the scout station.~~
   **Done** (commit `fab3ab1`, 2026-07-29 — `detection_ingest` moved to `8097`).
4. Document that all HTTP + MAVLink/RTP surfaces are plaintext by default; TAK TLS (`:8089`) is the
   only wired-in transport encryption.
