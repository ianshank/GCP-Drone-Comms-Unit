# Peer Review — "Implementation Plan (Validation-First)" + Regenerated Plan v2

> Reviewed 2026-07-04 against the working tree at the head of
> `claude/peer-review-implementation-plan-96e1m0` (includes merged PR #23). Every verdict
> below was checked against actual files, not docs alone. Part 1 is the claim-by-claim
> review; Part 2 is the regenerated plan with the corrections folded in.

## Part 1 — Peer review

### Overall assessment

The reviewed plan is a strong piece of analysis with one structural flaw: **it reviewed the
2026-06-30 baseline, and the tree has moved.** PR #23 (`74705ab`, `aac303c`, `b0d02a6`)
executed most of the plan's Stage 0 in the same commits that produced the repo's own
`IMPLEMENTATION_PLAN.md`, so several items the plan lists as open are shipped, and two of its
factual claims about missing tests/artifacts are wrong. Its core safety analysis, however,
survives review intact and remains the right headline.

What the plan got **right** (verified in code):

- The precision-landing publisher gap is real and stated precisely: `LANDING_TARGET` is off
  by default (`jetson_yolo_gcs/core/config.py` — `enable_landing_target: bool = False`),
  and there is **no autopilot-heartbeat gate, no cadence floor, and no stale-target
  suppression** anywhere in `mavlink/bridge.py` or `pipeline.py`. A publish failure is
  deliberately unguarded and crashes the camera loop (`pipeline.py`, "a failed safety-path
  publish must surface").
- The hardware-gating framing ([SW]/[HW] tags, falsifiable done-criteria) is the right
  structure and is kept in Part 2.
- FreeTAKUAS abandonment, the PX4 `LOCAL_NED` dialect requirement, the Hailo DFC x86-only
  constraint, and the insecure-by-default posture of mavlink2rest/FTS/raw TAK are all
  accurate and actionable.
- "No committed secrets" matches an independent scan of the tree and `.gitignore`; full-history
  `gitleaks` remains a worthwhile one-time confirmation.

### Claim-by-claim verdicts

| # | Plan claim | Verdict | Evidence |
| - | ---------- | ------- | -------- |
| 1 | NEXTSTEPS lists TLS CoT :8089, FTS pacing, Prometheus/JSON metrics, per-transport rx as open `[ ]` | **OVERTAKEN** | All four are ticked `[x]` in `docs/NEXTSTEPS.md` (Near-term M2 section) since `74705ab` |
| 2 | Initiative-C design doc is headed "NOT IMPLEMENTED" | **OVERTAKEN** | `docs/specs/initiative-c-commanding-design.md` now opens with an "IMPLEMENTED and unit-tested" status banner; the old header survives only as labeled history |
| 3 | Redundant `docs/NEXT_STEPS.md` duplicates/contradicts the canonical backlog | **PARTIALLY TRUE** | It existed but carried an explicit SUPERSEDED banner (neutralized, not contradicting). Deleted in this PR |
| 4 | `aiohttp<3.10` pin removed via injectable `HttpTransport` seam | **VERIFIED** | `pyproject.toml` extras use `aiohttp>=3.9`; seam landed in `aac303c`/`b0d02a6` |
| 5 | Test proving "a normal confirmation can never release force-disarm" is **missing** | **REFUTED** | It exists twice: `tests/test_command_safety.py` (`test_force_command_needs_force_ack_and_stays_staged_until_then`) and `tests/test_command_service.py` (`test_force_disarm_needs_force_ack`) |
| 6 | Command audit log has a "block-then-`LoggerOverflowError`" contract needing a soak test | **REFUTED (misattributed)** | That contract belongs to the FPV `FlightLogger` (`fpv/flight_logger.py`, tested in `test_fpv_logger.py`). The command sink `command/audit.py` `JsonlAuditLog` is a synchronous, fsync-durable writer with **no queue and no overflow semantics**. The real gap: only a fake-based propagation test exists (`test_command_lifecycle.py::test_audit_overflow_propagates_and_fails_closed`); no soak/adversarial exercise of the real sink (disk-full, slow-fsync, huge records) |
| 7 | Grafana golden-signal dashboard needs to be **created** at `ops/observability/grafana/…` | **REFUTED (already shipped)** | `ops/observability/grafana-meshsa-dashboard.json` + `ops/observability/README.md` exist, and the series-drift test the plan asked for already exists too (`tests/test_metrics.py::test_render_prometheus_emits_all_dashboard_metric_names`). Only the *path references* in NEXTSTEPS/IMPLEMENTATION_PLAN were stale (fixed in this PR) |
| 8 | CI Python matrix and pyproject pins "not directly readable" | **REFUTED** | Readable in-tree: matrix is `["3.10", "3.11", "3.12"]` for both `test` and `perception` jobs (`.github/workflows/ci.yml`); `pydantic>=2,<3`, `structlog>=23,<26`, `--cov-fail-under=90` confirmed verbatim in `packages/meshsa/pyproject.toml` |
| 9 | Landing-target publisher: no heartbeat gate / cadence floor; crash-on-publish-failure | **VERIFIED** | See "what the plan got right" above |
| 10 | No standalone M2 transport/endpoint auth-audit doc | **VERIFIED** | `docs/AUDIT_REPORT.md` is a coverage/quality audit, not an auth audit; the M2 audit exists only as a pending item |
| 11 | Inference lacks rate limiting, structured output parsing, offline queue | **VERIFIED** | `meshsa/inference.py`: retry/backoff exists, but no `min_interval_s`, no concurrency cap (unbounded `asyncio.create_task` per message), raw-string model output, failures dropped with a log |
| 12 | Hailo `.hef` backend is a stub behind the extension→backend registry | **VERIFIED** | `detection/hailo_backend.py` raises `NotImplementedError`; `factory.py` maps `.hef → "hailo"` |
| 13 | M3.1 richer tracks shipped; M3.2 sensor POI/FOV not | **VERIFIED** | `cot.py` `_emit_richer_detail` (track/status/vendor/attitude children) shipped; no POI/FOV emission exists (`cv/geo.py` projection is not surfaced as a CoT detail) |
| 14 | ~780 tests / ~99% coverage; gates green | **VERIFIED (fresh run)** | This checkout: meshsa **791 passed, 5 skipped, 99.10%** (gate 90); jetson_yolo_gcs **84 passed, 99.11%** (gate 85) |
| 15 | No "GCP ≠ Google Cloud Platform" note anywhere | **VERIFIED** | Added to the root README in this PR |

### Material findings the plan missed

1. **The heartbeat-gate pattern it prescribes already exists in-repo.** The commander refuses
   `arm` unless a **fresh autopilot heartbeat report** passes `arm_allowed()`
   (`command/service.py` + `command/safety.py`, fed by `MavlinkCommandPump` →
   `HeartbeatHealth`). The Jetson landing-target hardening should *mirror* this pattern, not
   design one from scratch — a much smaller, lower-risk change than the plan implies.
2. **Force-disarm has no in-flight interlock backstop.** `command/safety.py` states the reused
   `arm_allowed` predicate "gives no in-flight backstop against force-disarm." The double
   confirmation is the only guard. Whether that is acceptable is an explicit maintainer
   decision, not an implementation detail.
3. **Commander config bounds warn instead of reject** (`command/config.py`): out-of-range
   `ack_timeout_s`, `max_attempts`, `arm_report_max_age_s`, `target_system/component` log a
   warning and run; only `port` is hard-validated. On a command path, warn-vs-reject deserves
   a deliberate decision.
4. **`packages/meshsa/README.md` was the worst remaining doc drift** ("101 passed, 100%
   coverage" vs the real 791/99.1%) — the plan's doc-drift stage never mentioned it. Fixed in
   this PR.
5. The plan's own Stage 0 was **already executed by the commits that introduced the repo's
   IMPLEMENTATION_PLAN** — a reviewer acting on the plan verbatim would have redone finished
   work. Plans that ship alongside their own partial execution need explicit "as of commit X"
   baselines.

---

## Part 2 — Regenerated plan (v2, corrected)

Same validation-first structure; [SW] = executable in software now, [HW] = hardware-gated.
Each item keeps a falsifiable done-criterion. Baseline: head of this branch, 2026-07-04.

### Stage 0 — Baseline trust *(mostly complete; residuals fixed in this PR)*

- ~~Reconcile NEXTSTEPS/Initiative-C drift~~ — done in `74705ab`.
- ~~Confirm the green gate on a clean checkout~~ — re-confirmed 2026-07-04: meshsa 791
  passed / 99.10%, jetson_yolo_gcs 84 passed / 99.11%, on this container's fresh clone.
- Residuals closed by this PR: M3.1 checkbox ticked, Grafana artifact path references
  corrected, stale per-package README counts fixed, `docs/NEXT_STEPS.md` deleted, README
  "not Google Cloud" note added.
- **Remaining [SW]:** one-time full-history secret scan (`gitleaks detect` over all commits)
  to convert "no secrets found in tree" into "no secrets in history"; hang it on the existing
  `.pre-commit-config.yaml` going forward. *Done when:* scan output committed to the PR/issue
  record and the pre-commit hook is active.

### Stage 1 — Safety write-path gaps (headline; unchanged in priority)

1. **[SW] Harden the landing-target publisher by mirroring the commander's interlock.**
   ✅ **Software shipped (2026-07-04); on-vehicle [HW] validation still open.** A self-contained
   `jetson_yolo_gcs/mavlink/heartbeat.py::HeartbeatMonitor` mirrors `meshsa.command.health.HeartbeatHealth`
   (fail-closed, clock-injected, no meshsa import). `LandingTargetBridge.publish` now returns
   `bool` and **suppresses** (no send) until a fresh autopilot HEARTBEAT is polled via
   `poll_heartbeat` (filtered by `MAVLINK_TARGET_SYSTEM`/`_COMPONENT`, `0`=wildcard). The pipeline
   **counts + escalates** publish failures (`PIPELINE_PUBLISH_FAILURE_TOLERANCE`, default 3)
   instead of crashing the camera+stream loop, and counts **cadence-floor** violations against
   `MAVLINK_MIN_PUBLISH_RATE_HZ` (default 10). New config (all defaulted, no magic numbers):
   `MAVLINK_REQUIRE_HEARTBEAT` (default true), `MAVLINK_HEARTBEAT_TIMEOUT_S` (default 2 s).
   `MAVLINK_ENABLE_LANDING_TARGET` stays **false**. Fakes-only tests prove no publish on
   missing/stale heartbeat, escalation past tolerance, and cadence counting; the safety files
   are covered ≥98%. *Remaining:* CHARTER wording + `PLND_STRICT` note, and the [HW] bench pass.
2. **[SW] M2 transport/endpoint authentication audit doc** (prerequisite for any maintainer
   M2-gate clearance): enumerate every transport/surface and its actual auth posture — mutual
   TLS on `tak_tcp` (`_build_ssl_context`), bearer tokens on `meshsa.llm` and the commander,
   Meshtastic link-layer PSK (not endpoint auth), multicast (none), `/healthz`+`/metrics`
   (loopback default), mavlink2rest if deployed (none). *Done when:* a committed doc maps each
   surface → mechanism → residual risk, and no command-capable surface is exposable
   unauthenticated by default.
3. **[SW] Command-path adversarial completion** *(corrected scope — the force-ack test the
   original plan asked for already exists)*:
   - soak/adversarial tests of the **real** `JsonlAuditLog` (disk-full/`OSError` mid-append,
     fsync failure, sustained high-rate writes) proving the sender fails closed on audit
     failure with the real sink, not just a fake;
   - a maintainer decision + test on **force-disarm's missing in-flight backstop**;
   - a maintainer decision on config-bounds **warn vs reject** for the commander.
   *Done when:* tests exist for the chosen semantics and the two decisions are recorded in the
   design doc.

### Stage 2 — Finish M2 (productization)

4. ~~Grafana golden-signal dashboard + drift test~~ — **already shipped**
   (`ops/observability/grafana-meshsa-dashboard.json`, `ops/observability/README.md`,
   `test_metrics.py::test_render_prometheus_emits_all_dashboard_metric_names`). Residual
   [SW]: nothing; optional maintainer glance that the panel→signal mapping matches taste.
5. **[HW] Automated FTS end-to-end CI job** on a self-hosted Jetson runner, separate from the
   coverage gate (per IMPLEMENTATION_PLAN Track A.2). *Done when:* the job brings up FTS,
   publishes a track via the gateway, and asserts it via the FTS REST API + a multicast CoT
   listener.
6. **[HW] Soak/fuzz on real radios** + the cited-research pass on the four NEXTSTEPS
   "Unverified" items (MAVLink 2 signing, multi-GCS arbitration, arm64 signed-image/systemd
   hardening, Meshtastic store-and-forward semantics — ESP32-PSRAM-only, no default-channel
   support, duplicate delivery possible). *Done when:* findings doc committed before any
   dependent design.

### Stage 3 — Feature depth

7. **[SW] M3.2 richer tracks:** sensor Point-of-Interest / Field-of-View **natively in the
   `cot` codec** (surface the existing `cv/geo.py` pixel→ground projection as CoT detail;
   do not depend on abandoned FreeTAKUAS); deterministic stable UIDs for multiple simultaneous
   UAS. *Done when:* additive detail children render in ATAK with no schema bump and
   UID-stability tests pass across reconnects.
8. **[SW] Inference hardening** (IMPLEMENTATION_PLAN Track B): `min_interval_s` +
   `max_concurrent_requests` (semaphore + injectable clock), structured/JSON output parsing
   with raw-text fallback, multi-model env switch, bounded offline replay queue. *Done when:*
   fakes-only tests prove pacing, concurrency cap, and replay ordering; coverage stays ≥99%.
9. **[HW] Real Hailo-8 `.hef` backend** behind the existing extension→backend registry
   (`[hailo]` extra; models compiled on an x86 host — DFC is not ARM). *Done when:* `.hef`
   runs on Orin Nano + Hailo-8 at a documented FPS (~30–40 FPS YOLOv8n FP16 @640 expected).
10. **[HW] MAVLink-over-ELRS consolidation** (Betaflight ≥2025.12): evaluate reusing
    `mavlink_source` to retire the bespoke CRSF GPS decode. *Done when:* an ELRS MAVLink link
    produces an ATAK air track equivalent to the CRSF path.
11. **[SW→HW] PX4 `LOCAL_NED` landing-target dialect** (from NEXTSTEPS): `MAVLINK_FRAME`
    config + pixel→bearing→NED; first pin the current `landing_target_send` arity /
    `position_valid=0` behavior in a test. *Done when:* frame selection is config-driven and
    covered by fakes-only tests; PX4 bench validation is the [HW] tail.

### Stage 4 — Packaging / fleet (M4/M5)

12. Reproducible multi-arch (arm64) image, signed releases, GHCR publish on tags; dedicated
    `flightctl` service user; optional root-on-NVMe appliance build. *Done when:* a tagged
    release yields a reproducible signed image and a clean-boot appliance install.

### Standing thresholds

- If hardware is unavailable, every [SW] item above remains fully unblocked.
- If any command surface is to be exposed in a real deployment, Stage 1 items 1–3 become
  **blocking gates**, and the M2-gate clearance stays a recorded maintainer decision
  (CHARTER §6) — this plan does not clear it.
- If a secret is ever found in history, that becomes P0 over everything: rotate, rewrite
  history, add the gitleaks pre-commit hook.
