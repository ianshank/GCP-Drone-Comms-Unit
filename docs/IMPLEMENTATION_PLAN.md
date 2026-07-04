# Implementation Plan — Next Steps (spec-driven)

> **Status: WORKING PLAN (changeable).** This is a near-term, spec-driven execution plan
> derived from [CHARTER.md](CHARTER.md) (scope + invariants), [ROADMAP.md](ROADMAP.md)
> (milestone trajectory), and [NEXTSTEPS.md](NEXTSTEPS.md) (backlog). It sequences *how* the
> remaining work lands without changing scope. It does **not** amend the stable docs: where it
> finds drift or a scope question, it flags it for a deliberate human decision (CHARTER §6),
> it does not silently rewrite CHARTER/ROADMAP.
>
> Reading order for an agent picking up work stays: **CHARTER → ROADMAP → nearest scoped
> `AGENTS.md` → NEXTSTEPS → this plan → the relevant `docs/specs/*` spec.**

Generated: 2026-06-30. Baseline verified against the tree at that date (see §1).

---

## 0. How to use this plan

1. Pick a track (§3). Each work item is a **mini-spec**: the spec to author, the modules it
   touches, the invariants it must preserve, the test categories required, the coverage floor,
   the config fields it adds (no magic numbers), and its backward-compat posture.
2. **Author or update the full spec first** (§2, [specs/README.md](specs/README.md)). Code
   references the spec by section number in docstrings. No feature merges without a spec.
3. Implement behind the existing seams (registry, `Protocol`, config). Keep the gates green.
4. Update `CHANGELOG.md` and tick the item in `NEXTSTEPS.md` as it lands.

The invariants in [CHARTER.md](CHARTER.md) §4 gate every item below and are repeated as a
checklist in the spec template. They are non-negotiable: open/closed registry extensibility;
versioned backward-compatible wire; DI via `Protocol`; pure codecs; config-driven (no magic
numbers); green `ruff`/`ruff format`/`mypy --strict` + high-coverage suite; no secrets in repo.

---

## 1. Ground truth — code vs. docs reconciliation

The single most important finding from the 2026-06-30 baseline scan: **the codebase is well
ahead of the planning docs.** Several items NEXTSTEPS lists as open (`[ ]`) are shipped and
tested, and the Initiative-C design doc is still headed "NOT IMPLEMENTED" while the full
`meshsa.command` stack and `flightctl/run_commander.py` exist and are tested. Reconciling this
drift is **Track 0 (P0)** — agents that trust the stale docs will redo finished work or
mis-assess safety posture.

| Area | Docs say | Code reality (2026-06-30) | Action |
| ---- | -------- | ------------------------- | ------ |
| TLS CoT `:8089` | NEXTSTEPS open `[ ]` | **Shipped** — `transports/tak.py` has scheme parsing (`tls://`/`ssl://`/`tcp://`), `_build_ssl_context`, CA/client-cert, port 8089 default | Tick NEXTSTEPS; spec retro-doc |
| Pacing / rate-limit to FTS | NEXTSTEPS open `[ ]` | **Shipped** — `transports/pacing.py` (100% cov) | Tick NEXTSTEPS |
| Metrics export (Prometheus/JSON) | NEXTSTEPS open `[ ]` | **Shipped** — `metrics.py` `render_prometheus`, `HealthConfig` `/metrics` route | Tick; Grafana JSON still TODO |
| Per-transport rx observability | NEXTSTEPS open `[ ]` | **Shipped** — `PollingSourceTransport.rx_frames` + throttled link log | Tick NEXTSTEPS |
| M3.1 course/speed/battery/attitude | "Mid-term, planned" | **Shipped, additive, no schema bump** — `Position`/`Attitude`/`Telemetry`, detail-aware `CotCodec` | Tick; M3.2 remains |
| Initiative C commanding | design doc: **"NOT IMPLEMENTED"** | **Fully implemented + tested** — `meshsa.command.{commands,config,safety,audit,health,lifecycle,mavlink_link,mavlink_pump,service,errors}` + 9 test files + `flightctl/run_commander.py` (loopback+token, 4 endpoints) | **Correct the status banner (§Track 0); the safety design in the doc still governs** |
| Detection → CoT bridge (Init. D Phase A) | not in NEXTSTEPS | **Shipped** — `detection_ingest` transport + `detection_codec` + `cv/geo.py` + MARKER encode | Add to NEXTSTEPS |
| Inference MVP (Init. E) | NEXTSTEPS done `[x]` | Shipped, **but 9 tests currently RED in this env** (aiohttp 3.14 vs pin `<3.10`) | **Track 0 P0 — green the gate** |

**Verified baseline:** `cd packages/meshsa && python -m pytest` → 766 passed, **9 failed**, 5
skipped; total line+branch coverage **98.59%** (floor 90%). `jetson_yolo_gcs` gates green
(floor 85%). The 9 failures are all in `test_inference.py` / `test_inference_e2e.py` and stem
from `aiohttp 3.14.1` being installed against a `aiohttp>=3.9,<3.10` pin that the environment
did not honor — a brittle-pin smell, not a logic bug (see Track 0.1).

---

## 2. Spec-driven workflow (the operating rule)

"Spec-driven development" here means: **every roadmap/initiative item gets a committed spec
under `docs/specs/` before code lands, and the code cites the spec by section.** This is the
discipline already used for the FPV subsystem (`PHASE0_ERRATA.md`, `PHASE1_SPEC_v1_1.md` — code
docstrings reference `§5.1`, `§4.2`) and for Initiative C (`initiative-c-commanding-design.md`).
We generalize it:

1. **Author the spec** from [specs/TEMPLATE.md](specs/TEMPLATE.md). It must state scope,
   non-goals, the protocol/interface facts the implementation relies on, module specs, the
   config fields (every operational value — no magic numbers), the test plan by category, the
   backward-compat / schema posture, and the CHARTER §4 invariant checklist.
2. **Register it** in [specs/README.md](specs/README.md) with a status (`Definition` →
   `Implemented` → `Validated`).
3. **Implement** behind the seams; docstrings cite `§` numbers back to the spec.
4. **Validate**: gates green, coverage floor met per spec, CHANGELOG + NEXTSTEPS updated; flip
   the spec status to `Implemented` (and later `Validated` once hardware/bench criteria pass).

Specs that must be **authored or back-filled** (tracked per item in §3): inference hardening,
perception precision-landing safety, M3.2 richer-tracks (SPI/FoV + stable UIDs), detection→CoT
bridge (retro-spec), observability/metrics (retro-spec). Initiative-C's doc is back-filled to
`Implemented` status (Track 0.2).

---

## 3. The plan, by track

Priority order: **Track 0 (P0) → A → C → B → D → E → F.** Tracks A–F are largely independent
and can run in parallel worktrees (§5); Track 0 unblocks everyone (green gate + trustworthy
docs) and goes first.

### Track 0 — Make the baseline trustworthy (P0, do first)

**0.1 Green the inference gate without a brittle pin. ✅ DONE (2026-06-30).**
- *Problem (was):* `aiohttp>=3.9,<3.10` (`pyproject.toml` ×3) was a band-aid that broke the suite
  the moment the environment shipped a newer `aiohttp` (3.14.1) — the `aioresponses` mock's
  `ClientResponse` construction changed across aiohttp majors (`missing … 'stream_writer'`).
- *What landed:* the HTTP boundary is now an injectable `HttpTransport` `Protocol` (`HttpResponse`
  + default socket-backed `AiohttpTransport`; CHARTER §4.3/§4.4). `NemotronClient` /
  `InferenceService` / `build_node` accept an optional `transport=`; unit tests inject a pure
  `FakeHttpTransport` (no `aiohttp`, no sockets). The `<3.10` pin and `aioresponses` are removed.
  Non-2xx → `InferenceHttpError(status)`; transport/timeout → `InferenceTransportError`. Debug
  logging added on the request/retry path. Spec:
  [specs/initiative-e-inference.md](specs/initiative-e-inference.md) (status Implemented).
- *Result:* full suite **780 passed, 0 failed**; total coverage **99.09%**; `inference.py` **100%**
  line+branch; `ruff`/`ruff format`/`mypy --strict` clean; `python -m build` green. Backwards-
  compatible (callers passing no `transport` are unaffected).

**0.2 Reconcile docs with shipped code (no scope change).**
- Tick the shipped `[ ]` items in `NEXTSTEPS.md` (TLS, pacing, metrics, rx observability) and
  add the detection→CoT bridge entry under Perception.
- Add a **status banner** to `docs/specs/initiative-c-commanding-design.md`: the design still
  governs the safety layer, but the modules are implemented and tested — point to
  `meshsa.command.*` and `flightctl/run_commander.py`. Do **not** alter the safety design.
- Back-fill retro-specs (Implemented status) for: detection→CoT bridge, metrics/observability.
- **Flag for human decision (CHARTER §6):** ROADMAP marks Initiative C "ratified, gated on M2."
  M2's *TLS CoT* item shipped solidly (`transports/tak.py` mutual TLS); the command stack exists.
  But M2's gate is **transport/endpoint authentication**, and what actually exists is mutual TLS
  on the TAK transport plus per-endpoint bearer tokens on only two HTTP surfaces (`meshsa.llm`
  and the commander) — **not** transport-wide endpoint auth (e.g. Meshtastic relies on
  link-layer PSK, not endpoint auth). A **full M2 transport/endpoint-authentication audit** —
  enumerating every transport/surface and its actual auth posture — is itself a prerequisite
  task here, **before** any maintainer gate-clearance decision. This plan does **not** clear the
  gate unilaterally and does **not** assert transport-wide auth exists.
- **Redundant backlog file:** ✅ resolved 2026-07-04 — `docs/NEXT_STEPS.md` (with the
  underscore) was a separate, small, stale duplicate of the canonical `docs/NEXTSTEPS.md`;
  it has been deleted so there is a single canonical backlog.

*Exit:* `pytest` green (0 failed), NEXTSTEPS reflects reality, no agent is misled by a stale
"NOT IMPLEMENTED" header.

---

### Track A — Finish M2 hardening

The big pieces (TLS, pacing, metrics) shipped. What remains is field/CI validation and the
operator-facing observability surface.

**A.1 Grafana golden-signal dashboard (config artifact, not code).** ✅ shipped — see
`ops/observability/grafana-meshsa-dashboard.json` + `ops/observability/README.md`, with the
drift test in `tests/test_metrics.py::test_render_prometheus_emits_all_dashboard_metric_names`.
- *Spec:* observability retro-spec (0.2) gains a "dashboards" section mapping the existing
  `rx/tx/forwarded/dropped/reconnects` + per-transport series to the four golden signals.
- *Deliverable:* `ops/observability/grafana-meshsa-dashboard.json` (importable) + README.
- *No magic numbers:* dashboard variables (datasource, job, interval) are templated, not baked.
- *Invariants:* no new runtime dep; metrics names already stable in `metrics.py`.
- *Tests:* a sanity test asserting every `meshsa_*` series the dashboard references exists in
  `render_prometheus` output (guards dashboard/exporter drift) — pure, fakes-only.

**A.2 Automated FTS end-to-end (non-coverage CI job).**
- *Spec:* author `docs/specs/m2-fts-e2e.md` — bring up FreeTAKServer on a self-hosted Jetson
  runner; publish a track via the gateway; assert it via the FTS REST API + a multicast CoT
  listener. Pinned by `flightctl/constraints/fts-constraints.txt` (already exists).
- *Invariants:* this is an integration job, **separate** from the coverage gate (hardware glue
  is `# pragma: no cover`); the pure suite stays the coverage source of truth.
- *Tests:* the job itself is the test; add a fakes-only contract test for the REST assertion
  helper so the helper is unit-covered.

**A.3 Soak / fuzz on real radios + MAVLink 2 message signing research.**
- *Spec:* `docs/specs/m2-soak-fuzz.md` — duration, fault injection, pass/fail thresholds (all
  config, provisional until measured, like the FPV §8 calibration pattern).
- *Open research items from NEXTSTEPS "Unverified":* MAVLink 2 message signing, multi-GCS link
  arbitration, arm64 signed-image + systemd hardening, Meshtastic S&F semantics. Use the
  `deep-research` skill to produce a cited findings doc before committing to a design.

---

### Track B — Initiative E: inference hardening

Spec: **author `docs/specs/initiative-e-inference.md`** (back-fills the MVP + the 4 backlog
items). Active backlog from NEXTSTEPS:

**B.1 Local rate limiting** — add `min_interval_s` / `max_concurrent_requests` to
`NemotronConfig` (+ `MESHSA_INFERENCE_*` env bindings) so a burst of mesh traffic can't spike
API spend. Enforced with an injectable clock + semaphore. *No magic numbers* — both are config
fields with explicit defaults. Tests: fakes-only, `FakeClock`, assert pacing + concurrency cap.

**B.2 Structured response parsing** — parse the NVIDIA structured/JSON output instead of the raw
`content` string; fall back to raw text when JSON mode is unavailable. Keep a pure parser
function (testable without the network). Tests: golden vectors for both modes + malformed.

**B.3 Multi-model support** — select Nemotron model at runtime via `MESHSA_INFERENCE_MODEL`
(binding already exists); add validation + a documented allow-list so an unknown model fails
clearly. Backward-compat: default model unchanged.

**B.4 Offline fallback** — bounded queue of unsent messages, replay on reconnect, drop-and-count
on overflow (mirror the `FlightLogger`/router backpressure pattern, not a new one). Tests:
queue-full, reconnect replay ordering, never-block-the-pump.

Invariants throughout: lazy `aiohttp` import preserved; `aiohttp.ClientSession` reuse under the
existing `asyncio.Lock`; `[AI Insight]`-prefix feedback-loop filter preserved; `meshsa[inference]`
stays optional; base install untouched. Coverage floor: restore/maintain ≥99%.

---

### Track C — Initiative D: perception hardening (`jetson_yolo_gcs`)

Spec: **author `docs/specs/initiative-d-perception.md`** with a dedicated **precision-landing
safety section** (this is the write path — highest risk in this package). Scoped guide:
`packages/jetson_yolo_gcs/AGENTS.md`. Each item lands behind the registry/Protocol seams with
no pipeline edits.

**C.1 Precision-landing safety hardening (do first in this track).**
- Autopilot-**heartbeat gate** (fail-closed) before any `LANDING_TARGET` publish — reuse the
  `meshsa.command.health.HeartbeatHealth` *pattern* (not a runtime dep).
- **≥10 Hz cadence floor + stale-target suppression**; config fields
  `MAVLINK_MIN_RATE_HZ` / `MAVLINK_TARGET_STALE_S` (defaults explicit, no literals).
- Reconsider the in-flight publish-failure policy: count/escalate instead of crashing the
  camera+stream loop (the current "publish fails loud" policy stops the run — acceptable
  pre-flight, hazardous mid-approach; spec must state the chosen behavior and why).
- CHARTER wording note: advisory hint, authoritative for final approach once the operator opts
  in; document `PLND_STRICT` failsafe interaction.
- *Keep* `MAVLINK_ENABLE_LANDING_TARGET=false` default (off, opt-in, advisory).
- Tests: heartbeat-stale → no publish; cadence-floor enforcement; stale-target suppression;
  publish-failure escalation path — all fakes-only, no autopilot. Tighten patch coverage on
  `pipeline.py` + `mavlink/bridge.py` (the safety files).

**C.2 PX4 `LOCAL_NED` dialect** — `MAVLINK_FRAME` (`body_frd`|`local_ned`); pixel→bearing→NED
projection (FOV + attitude/alt + `GPS_GLOBAL_ORIGIN`). *First* add a pin test on the current
`landing_target_send` arg arity / `position_valid=0` default (lock current behavior before
extending). Reuse `meshsa.cv.geo` projection math where shared.

**C.3 TIMESYNC + capture-time `time_usec`** — align to the vehicle clock, then stamp frame
capture time; until then send `0` (documented). Config: enable flag + sync interval.

**C.4 Real Hailo-8 `.hef` inference** — implement the `hailo_backend` (currently a stub) behind
the existing extension→backend registry; add a `[hailo]` extra + an x86-host `.pt`→ONNX→`.hef`
model-prep note (DFC is not ARM). No pipeline edits — registry only.

**C.5 Live `/healthz` + watchdog** — optional `[health]` aiohttp listener (lazy in-function
import, mirroring `meshsa.health`); wire liveness → systemd `WatchdogSec`/`sd_notify`.

**C.6 On-device runbook** — TensorRT `.engine` export (FP16/INT8), NVMM-caps smoke, QGC RTP
smoke. Doc + `# pragma: no cover` device glue only.

---

### Track D — M3.2 richer tracks

M3.1 (course/speed/battery/attitude) shipped additively. Remaining, spec
`docs/specs/m3-richer-tracks.md`:

**D.1 Sensor Point-of-Interest / Field-of-View CoT** — implement SPI/FoV **natively in the
`cot` codec** (do not depend on the abandoned FreeTAKUAS). Needs pixel→geo / camera pose —
reuse `meshsa.cv.geo`. Additive detail children; **no schema bump** unless the envelope shape
changes (then run the full bump ritual via the `meshsa-schema-version-bump` skill).

**D.2 Multiple simultaneous UAS with stable UIDs** — deterministic UID derivation per vehicle;
tests assert stability across reconnects and no cross-talk.

**D.3 (Optional) Remote ID → CoT ingest** — a `DroneCOT`-style source transport via the
registry (ODID/DJI DroneID). Pure codec + injectable transport.

**D.4 (Optional) MAVLink-over-ELRS consolidation** — reuse `mavlink_source` for the Betaflight
2025.12+ MAVLink-over-ELRS path; could retire the bespoke CRSF GPS decode. Research first.

---

### Track E — Initiative C: close the loop

The command stack is implemented and tested. Remaining work is **governance + completeness**,
not a greenfield build:

**E.1** Promote `initiative-c-commanding-design.md` from "design only" to an `Implemented` spec
(status banner in Track 0.2; full pass once the maintainer rules on the M2 gate).
**E.2** Confirm the whitelist-first ordering is enforced by default (`allowed = {set_mode, rtl}`)
and that force-disarm (`param2=21196`) stays behind its separate confirmation + off-by-default
flag — add/keep adversarial tests for "normal confirm must never release a force command."
**E.3** Command-channel auth review against the M2 TLS posture before any non-loopback bind is
documented for deployment. The commander HTTP surface today has endpoint auth (bearer token,
loopback-default, fail-closed) — as does `meshsa.llm` — but this is **per-endpoint** auth on two
HTTP surfaces, not transport-wide M2 auth; the review is part of the full M2
transport/endpoint-authentication audit (Track 0.2), not a settled posture. Keep `meshsa.llm`
read-only.
**E.4** Audit-log durability soak: assert the block-then-`LoggerOverflowError` contract holds
under sustained overflow (never silently drops an audit record).

> ⛔ No deployment exposes a command surface off-loopback without the M2 auth/TLS layer in
> front of it. This plan does not change that gate. TLS CoT shipped on the TAK transport, and
> endpoint auth exists for the `meshsa.llm` and commander HTTP surfaces (bearer token,
> loopback-default, fail-closed) — but that is **not** transport-wide M2 auth. Before any
> clearance the maintainer needs the full M2 transport/endpoint-authentication audit (Track 0.2);
> this plan does not assert the auth building blocks are complete.

---

### Track F — M4 / M5 fleet & packaging

Lower priority; spec each before building.

**F.1** Meshtastic **store-and-forward** for intermittent links (research semantics first —
flagged "Unverified" in NEXTSTEPS). Spec `docs/specs/m4-store-and-forward.md`.
**F.2** Reproducible **multi-arch (arm64) image** + signed releases + GHCR publish on tags
(workflow scaffold exists). Spec `docs/specs/m5-packaging.md`.
**F.3** Root-on-NVMe appliance build (removes the eMMC constraint).
**F.4** systemd enablement with a dedicated `flightctl` service user + correct SSD-venv
ownership.

---

## 4. Agent & skill modernization

The harness (`.agents/skills`, `.github/agents`) lagged the code: it had no skill for the
safety-critical command path, the whole perception package, the observability surface, the
inference bridge, or the spec-driven workflow itself. **This PR brings them up to date** and
adds what was missing.

**Skills added** (`.agents/skills/`, format matches the existing six):

| Skill | Use when |
| ----- | -------- |
| `spec-driven-change` | Starting any roadmap/initiative feature — author/update a spec first |
| `meshsa-commanding-safety` | Touching the supervised command path (Initiative C): safety/auth/audit/health, force-disarm gate, whitelist |
| `jetson-perception` | Working in `packages/jetson_yolo_gcs`: add a detector backend, pipeline failure policy, `LANDING_TARGET` safety |
| `meshsa-observability` | Metrics/health export: `RouterMetrics`, `render_prometheus`, golden signals, Grafana |
| `meshsa-inference` | The Nemotron bridge: lazy aiohttp, session-reuse lock, feedback-loop filter, env config, test-mock compat |

**Custom agents added** (`.github/agents/`):

| Agent | Focus |
| ----- | ----- |
| `meshsa-perception.agent.md` | `jetson_yolo_gcs` implementation (self-contained, no meshsa dep) |
| `meshsa-commanding.agent.md` | Initiative-C command path with the safety layer foregrounded |

Discoverability surfaces updated: `.agents/README.md` skills table and the root `AGENTS.md`
"Agent Skills" / "Custom Agents" lists. Existing skills (`meshsa-add-transport`,
`meshsa-add-codec`, `meshsa-schema-version-bump`, `meshsa-test-conventions`,
`ops-deploy-base-node`, `pre-pr-validator`) remain accurate and are unchanged.

**Still worth adding later** (out of scope for this PR, listed so it isn't lost): an
`ops-observability` deploy skill once the Grafana artifact (A.1) lands; a `meshsa-fpv` skill if
the FPV bench-validation work (NEXTSTEPS §8) resumes.

---

## 5. Executing with worktrees, sub-agents, and MCPs

Tracks A–F are independent and parallelizable. Recommended mechanics:

- **Worktrees / isolation:** run each track in its own git worktree so parallel agents editing
  different packages (`meshsa` vs `jetson_yolo_gcs`) never collide. Use the `Plan` agent to
  draft a track's spec, then `general-purpose`/framework agents to implement.
- **Sub-agents:** use the `Explore` agent for read-only fan-out (e.g. "find every config field
  that lacks an env binding"); use the focused custom agents (`meshsa-framework`,
  `meshsa-perception`, `meshsa-commanding`, `meshsa-ops`, `meshsa-review`) for scoped edits.
- **Skills:** invoke the matching skill at the start of each item (e.g. `meshsa-add-codec` for
  D.1, `jetson-perception` for Track C, `spec-driven-change` for every spec).
- **MCPs:** `deep-research` / WebSearch+WebFetch for the "Unverified" research items (MAVLink 2
  signing, S&F semantics) before committing to a design; Hugging Face MCP for model/dataset
  lookups when selecting detector weights (Track C.4); GitHub MCP for PRs/CI.
- **Gate every track** with `pre-pr-validator` before opening a PR.

---

## 6. Sequencing & dependencies

```
Track 0 (P0: green gate + reconcile docs)   ── unblocks everything
   ├─► Track A (M2 finish: Grafana, FTS e2e, soak/fuzz + signing research)
   ├─► Track B (inference hardening)         ── depends on 0.1 (green inference gate)
   ├─► Track C (perception safety → PX4/TIMESYNC/Hailo → runbook)  C.1 before C.2–C.6
   ├─► Track D (M3.2 richer tracks)          ── D.1 reuses cv.geo (shared w/ C.2)
   ├─► Track E (commanding: governance + completeness)  ── gated on maintainer M2 ruling
   └─► Track F (M4/M5 fleet & packaging)     ── research-gated (S&F semantics)
```

`cv/geo.py` is shared by C.2 (NED projection) and D.1 (SPI/FoV geo) — coordinate those two so
the projection math has one home.

---

## 7. Risks & watch-items

- **Doc drift is the headline risk.** Until Track 0.2 lands, agents reading the stale
  Initiative-C header or unticked NEXTSTEPS items will misjudge state. Do Track 0 first.
- **Brittle dependency pins** (`aiohttp<3.10`) break the gate under environment drift; widen +
  make test doubles version-tolerant rather than chasing pins (0.1).
- **Insecure-by-default building blocks** (`mavlink2rest`, FreeTAKServer, raw TAK transports)
  stay unauthenticated/plaintext out of the box — any command/field deployment adds the
  auth/TLS/confirmation layer first (CHARTER §3; Track E gate).
- **Safety write paths** (`jetson_yolo_gcs` `LANDING_TARGET`, the command path) carry the most
  risk — they get specs with explicit safety sections and adversarial tests *before* extension.
- **Unverified research items** (MAVLink 2 signing, multi-GCS arbitration, arm64 signed-image +
  systemd hardening, Meshtastic S&F) must be researched and cited before design — do not build
  on assumptions.
- **Scope discipline:** mission/waypoint autonomy, swarm, and BVLOS stay out of scope pending a
  separate CHARTER §6 amendment. If an item seems to require expanding scope or relaxing an
  invariant, stop and surface it.
