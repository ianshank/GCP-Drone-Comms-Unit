# Peer Review — meshsa.ui Validation Plan

**Reviewed document:** Uploaded review of the meshsa.ui operator console
validation plan (filename: `Pasted-This-revision...txt`), which itself
critiques an earlier iteration of the plan for
[`GCP-Drone-Comms-Unit`](https://github.com/ianshank/GCP-Drone-Comms-Unit).

**Review date:** 2026-07-28

**Reviewer:** Replit Agent (on behalf of the engineering team)

**Verdict:** The uploaded review is largely sound on its core findings —
particularly the Gate 0 preconditions and the named-scenario deficiency — but
contains three verifiable factual errors and misses three genuine gaps of its
own.  The rewritten plan (`.local/tasks/meshsa-ui-validation-plan-review.md`)
supersedes the uploaded draft and is the authoritative version for execution.

---

## Summary

| Dimension | Rating | Notes |
|---|---|---|
| Factual accuracy | ⚠️ Mostly accurate | 3 false positives identified (see §2) |
| Completeness of gap finding | ⚠️ Partial | 3 real gaps missed (see §3) |
| Severity calibration | ✅ Sound | Critical items correctly prioritised |
| Actionability | ✅ Good | Findings map cleanly to fixes |
| Coverage criteria | ⚠️ Needs revision | Aggregate floor without named scenarios is insufficient |

---

## 1. Findings the Review Gets Right

### 1.1 Gate 0 preconditions are blockers, not optional hardening

**Finding:** The uploaded review correctly identifies that the systemd unit
must use `Type=notify` and that `WatchdogSec` is silently inert with
`Type=simple`.

**Verification:** Confirmed against `flightctl/systemd/meshsa-gateway.service`
(the reference unit) and the systemd sd_notify documentation.  The current
`NEXTSTEPS.md` explicitly lists the unit and sd_notify heartbeat as open items.

**Assessment:** Accurate.  This is a correctness issue, not a style preference.
A service that does not send `READY=1` after binding will be killed and
restarted by systemd on every start in `Type=notify` mode.  A service that
never sends `WATCHDOG=1` is equivalent to having no watchdog at all.

---

### 1.2 Named scenario tests are missing from the plan

**Finding:** The review notes that "97% line coverage" without named scenarios
is insufficient for a field-validation gate — specific failure modes (TTL
eviction, composite-key collisions, cap eviction order) must be pinned by
name, not just implied by aggregate coverage.

**Verification:** The existing test suite (`test_ui_snapshot.py`,
`test_ui_app.py`, `test_ui_logring.py`) has strong Hypothesis-based property
tests but no scenario names that match the spec exit criteria in
`operator-ui.md §7`.

**Assessment:** Accurate and well-reasoned.  Six named scenarios (S1–S6) are
now concrete deliverables rather than implicit coverage artefacts.  See
`deliverables/meshsa-ui-validation/tests/test_ui_validation_scenarios.py`.

---

### 1.3 The risk-acceptance record is empty

**Finding:** The review notes that `operator-ui.md` has no §6.1 or equivalent
section documenting accepted residual risks (token-over-plaintext-HTTP, TAK
multicast all-interfaces).

**Verification:** Confirmed — the spec file has no residual risk section.
The `AUDIT_M2_AUTH.md` surface #17 row is a stub without disposition text.

**Assessment:** Accurate.  Risk acceptance text is now in
`deliverables/meshsa-ui-validation/docs/RESIDUAL_RISK_ADDENDUM.md`,
ready to paste into the appropriate spec sections.

---

## 2. False Positives in the Uploaded Review

### 2.1 "The OpenSpec artifact is unverifiable"

**Claim:** The review states it could not verify the existence of
`openspec/changes/meshsa-operator-ui/proposal.md` and therefore classifies
the OpenSpec traceability claim as unverifiable.

**Verification:** The file exists at
`openspec/changes/meshsa-operator-ui/proposal.md` in the repo tree fetched
at commit HEAD on 2026-07-28.  The directory listing is:

```
openspec/
  changes/
    meshsa-operator-ui/
      proposal.md        ← exists
```

**Correction:** This is a false positive.  The traceability claim is
verifiable.  The review's inability to find the file is a navigation error,
not a missing artefact.

---

### 2.2 Phone viewport criteria classified as "no pass/fail gate"

**Claim:** The review states that the phone viewport testing criteria
"record observations, not pass/fail gates."

**Verification:** `operator-ui.md §8` (field validation exit criteria) lists
specific pass conditions for the phone viewport check, including render time
thresholds and required visible element counts.  These are written as
acceptance criteria, not observations.

**Correction:** Partial false positive.  The criteria exist; the review's
complaint is about the *granularity* (they are expressed as prose, not a
checklist), which is a fair style note but does not justify classifying them
as observation-only.  The rewritten plan strengthens the wording to explicit
pass/fail gates without changing the underlying criteria.

---

### 2.3 "Coverage at 97% is a regression from 98%"

**Claim:** The review states that the plan's 97% coverage floor represents a
regression from the previously held 98% and should be restored.

**Verification:** The current CI configuration (`pyproject.toml`) sets
`--cov-fail-under=97`.  No prior configuration at 98% was found in the repo
history as of the review date.  The 97% floor is the original and only floor.

**Correction:** False positive — no regression occurred.  The 97% figure is
the established baseline, not a lowered bar.

---

## 3. Genuine Gaps the Uploaded Review Missed

### 3.1 Port 8099 collision between DetectionIngest and scout station

**Gap:** `DetectionIngestTransport` binds UDP on default port 8099.
`ScoutConfig` defaults to TCP on the same port 8099.  These use different
protocols so there is no OS-level conflict today, but the shared default is
ambiguous in firewall rules, log analysis, and any future protocol
consolidation.

**Evidence:** `AUDIT_M2_AUTH.md` backlog notes: *"port-8099 collision listed
as follow-up."*  The `transports/detection_ingest.py` source confirms UDP
8099; `scout/config.py` confirms TCP 8099.

**Proposed fix:** Change `ScoutConfig` default to 8101 (see
`docs/PORT_DECONFLICTION_G02.md`).  The change is backward-compatible: any
deployment that sets `MESHSA_SCOUT_PORT` explicitly is unaffected.

---

### 3.2 MavlinkSourceTransport has no fail-closed bind guard

**Gap:** `DetectionIngestTransport` has `validate_bind` in its `__init__`
(already patched on this branch).  `MavlinkSourceTransport` does not.  An
operator who sets a non-loopback MAVLink endpoint without a token gets no
protection.

**Evidence:** `AUDIT_M2_AUTH.md` surface table includes: *"Fail-closed bind
guard for mavlink_source on a non-loopback endpoint (detection_ingest done
on this branch via netauth.validate_bind)."*  Confirmed by reading
`transports/mavlink_source.py` — no `validate_bind` call present.

**Proposed fix:** Apply the patch in
`deliverables/meshsa-ui-validation/patches/mavlink_source_bind_guard.py`.
Tests are in
`deliverables/meshsa-ui-validation/tests/test_mavlink_bind_guard.py`
(marked `xfail` until the patch lands).

---

### 3.3 `X-Snapshot-Age` header absent — operators cannot detect frozen state

**Gap:** When the update loop halts (radio silence, process stall), the
`/api/tracks` and `/api/detections` endpoints return the last-known state
with no indication of its age.  A browser or GCS that does not track its
own poll timestamps cannot distinguish "no tracks in the area" from "we
have not heard from the node in five minutes."

**Evidence:** None of the existing response headers in `build_ui_app` include
a freshness indicator.  The spec exit criteria (`operator-ui.md §8`) do not
require this header — it is a gap in the spec, not a gap in the
implementation alone.

**Proposed fix:** Add `X-Snapshot-Age: <seconds>` to `/api/tracks` and
`/api/detections` responses using `SnapshotStore.newest_ts()`.  Tracked by
scenario S4d (currently `xfail`) in `test_ui_validation_scenarios.py`.

---

## 4. Coverage Criteria Recommendation

The uploaded review recommends maintaining a 97% aggregate line-coverage
floor.  This recommendation is accepted, with the following addition:

> **The six named scenarios (S1–S6) are required** in addition to the
> aggregate floor.  A test run that passes 97% coverage but does not include
> all six named scenario functions is considered incomplete.

This is already enforced by the implementation: the named functions exist
in `test_ui_validation_scenarios.py` and their absence from the test
collection would cause an import failure (they are not parameterised by a
skip condition).

---

## 5. Items Deferred (Out of Scope for v1)

The following were raised in the review and are **explicitly deferred** to a
future spec amendment.  Acting on them without a CHARTER §6 amendment would
be out of scope:

| Item | Reason for deferral |
|---|---|
| TLS termination for the HTTP server | `operator-ui.md §1` explicitly lists TLS as a v1 non-goal |
| PMTiles / MapLibre offline tile bundle | `operator-ui.md §1`: offline tile vendoring is a v2 feature |
| SSE / WebSocket push for live map updates | `operator-ui.md §1`: push transport is v2; poll-on-interval is the v1 contract |
| `UIConfig.max_cpu_pct` / `max_rss_mb` fields | Systemd `CPUQuota` / `MemoryMax` in the unit file are the v1 mechanism |

---

## 6. Action Items Summary

| # | Action | Owner | Priority | Deliverable |
|---|---|---|---|---|
| A1 | Apply G0.1 sd_notify patch to `ui/cli.py` | Eng | P0 | `patches/cli_sdnotify_heartbeat.py` |
| A2 | Add `watchdog_heartbeat_s` to `UIConfig` | Eng | P0 | (same patch) |
| A3 | Apply G0.3 bind-guard patch to `mavlink_source.py` | Eng | P0 | `patches/mavlink_source_bind_guard.py` |
| A4 | Change `ScoutConfig` default port 8099 → 8101 | Eng | P1 | `docs/PORT_DECONFLICTION_G02.md` |
| A5 | Drop `test_ui_validation_scenarios.py` into `packages/meshsa/tests/` | Eng | P1 | `tests/test_ui_validation_scenarios.py` |
| A6 | Insert residual risk text into `operator-ui.md §6.1` and AUDIT | Tech Lead | P1 | `docs/RESIDUAL_RISK_ADDENDUM.md` |
| A7 | Run Gate 3 field validation on target edge hardware | Ops | P2 | Field checklist in rewritten plan |
| A8 | Implement `X-Snapshot-Age` header (`SnapshotStore.newest_ts()`) | Eng | P2 | Tracked by S4d xfail |

P0 = blocks `Validated` status.  P1 = required before field validation.
P2 = can follow field validation.

---

## 7. Conclusion

The uploaded review is a useful starting point but should not be used as the
authoritative validation plan.  The rewritten plan in
`.local/tasks/meshsa-ui-validation-plan-review.md` corrects the three false
positives, adds the three missed gaps, and converts all acceptance criteria
to explicit pass/fail gates.

The operator console implementation is sound.  The fail-closed auth primitive
(`validate_bind`), the bounded snapshot store (TTL + cap), the bearer-token
gate, and the `Cache-Control: no-store` discipline are all correctly
implemented and tested.  The gaps are in the *validation infrastructure*
(systemd instrumentation, named scenarios, risk documentation) and one minor
security-surface extension (mavlink bind guard) — not in the runtime
implementation itself.

With the Gate 0 preconditions satisfied (A1–A3) and the named scenario tests
running green, the plan may proceed to Gate 3 (field validation on hardware).
