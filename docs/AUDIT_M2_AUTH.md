# M2 Transport / Endpoint-Authentication Audit

<!-- markdownlint-disable MD013 MD060 -->

Date: 2026-07-08; surface inventory re-derived and corrected 2026-07-31 (see
[CHARTER_ALIGNMENT_AUDIT_PLAN.md](CHARTER_ALIGNMENT_AUDIT_PLAN.md) Phase D — this file's rows #10/#11
and two Gap-summary items were stale against commit `fab3ab1`, landed 2026-07-29 after the original
audit date).
Scope: **every socket-bound or link-bound surface in the repository**, and its actual
authentication / encryption posture. Widened 2026-09-25 from the original
`packages/meshsa` + `packages/jetson_yolo_gcs` scope: the ROADMAP M2 invariant ("no
unauthenticated surface is exposed by default") is repo-wide, so a `packages/`-only
inventory could not evidence it. Rows #18–#20 were added by that widening and were never
previously in scope — they are a **scope gap, not a regression**. Rows #21–#25 were
added 2026-10-27 by the code-quality reflection pass
([CODE_QUALITY_TECH_DEBT_PLAN.md](CODE_QUALITY_TECH_DEBT_PLAN.md) P0-8): two shipped
credential defaults (#21, #22 — both now closed) and three more unauthenticated
all-interfaces surfaces in shell/TS configuration (#23–#25 — recorded, not remediated).
Note that
`tools/claude_hooks/bind_guard.py::SCAN_GLOBS` is Python-only
(`packages/**/src/**/*.py`, `flightctl/**/*.py`, `tools/**/*.py`), so TypeScript and shell
listeners are outside its reach and are audited here by inspection only.
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
| 18 | TS API server — `artifacts/api-server/src/index.ts`, `src/app.ts` | Inbound listener | `app.listen(port, cb)` with **no host argument** ⇒ **all interfaces**; `PORT` is required and throws when unset (that gates startup, not exposure) | **None.** `src/middlewares/` holds only `.gitkeep`; `app.use(cors())` is unrestricted-origin. Sole route is `GET /api/healthz` returning `HealthCheckResponse.parse({status:"ok"})` — no data path, no mutation, no DB access despite the `@workspace/db` dependency | Plaintext HTTP | **Fails open.** *Severity context:* the exposed surface is one unauthenticated static health route, and `.replit-artifact/artifact.toml` (`localPort = 8080`, `paths = ["/api"]`) deploys it behind the platform proxy, where an all-interfaces bind **inside the container** is required. Comparable to rows #5/#9's open `/healthz`, not to a data surface |
| 19 | MAVLink router ingress — `flightctl/scripts/start_all.sh` (`mavp2p` ingress, `MAVP2P_IN_PORT`) | Inbound listener (UDP) | `udps:0.0.0.0:$MAVP2P_IN_PORT`, default **14550** ⇒ **all interfaces** | **None** — unsigned MAVLink ingest. Note this sits two lines below the script's own comment warning that a `0.0.0.0` bind for mavlink2rest *"would be a command-injection vector"*; that reasoning was applied to `M2R_BIND` (loopback default, row #20's sibling) but not to the router's own ingress | Plaintext UDP | **Fails open.** The most serious of #18–#20: anything on the LAN can inject MAVLink into the router, which fans out to the gateway and mavlink2rest |
| 20 | FreeTAKServer Web UI — `flightctl/scripts/start_all.sh` (`FTS_UI_EXPOSED_IP`) | Inbound listener | `FTS_UI_EXPOSED_IP=0.0.0.0`, port `$FTS_UI_PORT` default **5000** ⇒ **all interfaces** | FreeTAKServer's own UI auth (external to this repo; not verified here). `FTS_UI_WSKEY` is set to the literal placeholder `YourWebsocketKey` in the script | Plaintext HTTP | **Fails open** with respect to this repo's controls — the bind is unconditional, with no `validate_bind` equivalent and no token gate owned here |
| 21 | ATAK client AP passphrase — `ops/pi5-node/setup_pi5_node.sh` (`AP_PSK` → hostapd `wpa_passphrase`) | Inbound (Wi-Fi AP, WPA2-PSK) | `wlan0`, SSID `gcs-mesh` | WPA2-PSK. **Was** the shipped literal `change-me-please`, not env-overridable, so an unedited run brought the AP up on a published passphrase. **NOW** required from the environment (`${AP_PSK:?}`), no default (P0-8, 2026-10-27) | WPA2/CCMP | **NOW fails closed** — provisioning aborts before `hostapd.conf` is written; *was open by default* |
| 22 | WebMap → FTS REST credential — `flightctl/scripts/start_all.sh` (`FTH_FTS_API_Auth`) | Outbound client credential (Node-RED → FTS API `:19023`, loopback) | n/a | **Was** a fallback to `token`, FreeTAKServer's upstream default SystemUser API token. **NOW** no fallback: read from `fts.env`/environment, WebMap skipped with an error line when unset (P0-8, 2026-10-27) | Plaintext HTTP on loopback | **NOW fails closed** (skip, never a default credential); *was open by default* |
| 23 | FreeTAKServer CoT / REST / data-package listeners — `flightctl/systemd/fts.env.example` (`FTS_USER_ADDRESS`, `FTS_API_ADDRESS`, `FTS_DP_ADDRESS`) | Inbound listeners | `0.0.0.0` on `8087` / `19023` / data-package port, **as shipped in the example** | FreeTAKServer's own auth (external to this repo; not verified here); none owned here | Plaintext CoT/HTTP; TLS CoT on `8089` opt-in | Open with respect to this repo's controls — FTS is the intended ATAK ingress, so all-interfaces is the deployment, not an accident. **Recorded, not remediated**; same treatment as #18 |
| 24 | mavp2p ingress via systemd — `flightctl/systemd/mavp2p.env.example` (`udps:0.0.0.0:14550`) | Inbound (UDP) | all interfaces | **None** — unsigned MAVLink ingest | Plaintext UDP | Same gap as #19 (this is its systemd twin; row #19 cites only `start_all.sh`). Backlog item 5 must cover both files |
| 25 | mockup-sandbox Vite dev/preview server — `artifacts/mockup-sandbox/vite.config.ts` (`host: "0.0.0.0"`, `allowedHosts: true`) | Inbound listener (dev tooling) | all interfaces, both `server` and `preview` | **None** | Plaintext HTTP | Open. Replit-era dev tooling that T-2.3b archives; outside `bind_guard`'s Python-only scope like #18. **Recorded, not remediated** |

## Gap summary

- **Re-derived fail-open surface count (2026-09-25): 6 rows, of which 4 are genuine
  unauthenticated inbound listeners.** The authoritative figure is the **6 surface-inventory
  rows** whose Fail-closed column reads "fails open".
  - **The session-start banner's number is always larger and is not a surface count.**
    `.claude/hooks/session-start.sh` runs `grep -ci 'fails open'` over this file, so it also
    counts every prose mention — including the sentence you are reading. That makes the total
    self-referential: editing this bullet changes it. Do **not** write the banner's number into
    this document, which is how the previous version of this bullet came to assert 6 while the
    banner printed 9. Compare row counts, not grep counts.
  The 6 rows are #1 `TakTcpTransport`, #2
  `TakMulticastTransport`, #4 `MeshtasticTransport`, and the three added when this document's
  scope widened to the whole repository — #18 TS API server, #19 mavp2p ingress, #20
  FreeTAKServer Web UI.
  - **#1 and #4 are not listeners at all** — #1 is an outbound TLS client connection and #4 is
    serial/BLE or an outbound `TCPInterface` connect — so their "fails open" language describes
    plaintext/PSK-not-enforced *encryption* posture, not a bind gap. Neither is scanned by
    `bind_guard` by construction.
  - **#2** is a listener, in `bind_guard`'s scope, and a declared still-valid governance
    exception (`.claude/governance.yaml::bind_guard.exceptions`, "multicast CoT binds all
    interfaces — inherent to the protocol").
  - **#18, #19 and #20 are unauthenticated inbound listeners on all interfaces, and none of
    them has ever been in any mechanical control's scope**, because `bind_guard::SCAN_GLOBS` is
    Python-only (`packages/**/src/**/*.py`, `flightctl/**/*.py`, `tools/**/*.py`) and these are
    TypeScript and shell. That scope mismatch — not any single omission — is why they went
    unrecorded. **#19 is the serious one**: unsigned MAVLink ingest on `0.0.0.0`, two lines
    below the same script's comment warning that a `0.0.0.0` bind "would be a command-injection
    vector". **#18 is the mildest**: one static `GET /api/healthz`, no data path, and its
    `.replit-artifact/artifact.toml` deploys it behind a platform proxy where an
    all-interfaces bind *inside* the container is required.
  - These three are **recorded, not remediated.** Recording a surface is not authenticating it.
    See the follow-up backlog.
  - **2026-10-27 addendum (rows #21–#25).** #21 (`AP_PSK="change-me-please"`) and #22
    (`FTH_FTS_API_Auth` defaulting to FreeTAKServer's public SystemUser token) were
    *credential* defaults rather than binds, and are now closed: the passphrase is
    required from the environment and the token has no fallback. #23 (the shipped
    `fts.env.example` binds every FTS listener on `0.0.0.0`), #24 (`mavp2p.env.example`,
    the systemd twin of #19) and #25 (the mockup-sandbox Vite server) are three more
    all-interfaces listeners outside `bind_guard`'s scope, recorded with the same
    "accepted, not remediated" treatment as #18. The row-count figure above (6) is
    unchanged by #21/#22; #23–#25 are open listeners but are counted here, not in that
    bullet's Fail-closed-column tally, because their column does not use its phrase.
  - Superseded statement, kept so the change is auditable: this bullet previously read
    "3 [rows], and only 1 … is an actual `bind_guard`-scoped listener gap … No new bind surface
    has appeared since 2026-07-08." That was true of the old two-package scope and is false
    under the repo-wide scope declared above.
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
  (`netauth.py::authorize`) and consistent fail-closed bind validation, shared by all five
  **`packages/meshsa` Python** HTTP surfaces. Scoped deliberately: rows #18 and #20 are HTTP
  surfaces outside that set — TypeScript and FreeTAKServer respectively — and neither routes
  through `netauth`, so "all HTTP surfaces" would be false under this document's repo-wide scope.
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
exists and **fails closed on all five `packages/meshsa` HTTP surfaces** — but not on the two
HTTP surfaces outside that package that this document's widened scope brought in (#18 TS API
server, #20 FreeTAKServer Web UI), neither of which routes through `netauth`. Further, three
unauthenticated all-interfaces listeners (#18, #19, #20) sit outside every mechanical control,
because `bind_guard` scans Python only. But this is **per-surface** auth, **not
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
5. **Bind mavp2p's ingress to loopback, or authenticate it (#19).** `udps:0.0.0.0:14550` accepts
   unsigned MAVLink from any interface. Highest-severity item in this list: it is the command
   path's ingress, and the same script's own comment calls a `0.0.0.0` bind for the sibling
   service "a command-injection vector". Needs its own change — a bind narrowing here alters
   the bring-up contract described at `flightctl/scripts/start_all.sh` lines 9-13.
6. **Narrow `FTS_UI_EXPOSED_IP` from `0.0.0.0` (#20), or document the deployment as
   trusted-network-only.** Note `FTS_UI_WSKEY` ships as the literal placeholder
   `YourWebsocketKey`.
7. **Decide the `artifacts/api-server` posture (#18).** The all-interfaces bind is *required*
   inside its container by the Replit platform proxy, so the fix is not a host argument — it is
   deciding whether that deployment model is in M2's scope at all, and recording the answer.
8. **Extend `bind_guard` beyond Python, or state that TypeScript and shell listeners are
   review-only.** `SCAN_GLOBS` is Python-only, which is the structural reason #18-#20 were
   never surfaced. Until one or the other happens, every non-Python listener in this repository
   depends entirely on a human noticing it.
9. ~~**Shipped credential defaults (#21 `AP_PSK`, #22 `FTH_FTS_API_Auth`).**~~ **Done**
   (P0-8, 2026-10-27): `setup_pi5_node.sh` requires `AP_PSK` from the environment;
   `start_all.sh` has no token fallback and skips the WebMap when unset.
10. **Decide the posture of the shipped FTS example binds (#23) and narrow or document the
    mavp2p systemd twin (#24) together with #19.** The `fts.env.example` comment already says
    "set `FTS_*_ADDRESS` to the Jetson LAN IP for remote ATAK"; it should say that the
    `0.0.0.0` it ships is a trusted-network-only choice. #25 (Vite dev server) is resolved by
    T-2.3b's archive rather than by a bind change.
