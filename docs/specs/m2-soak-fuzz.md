# M2 Soak/Fuzz — link-loss resilience under availability attack

> **Status: Implemented (bench §8 pending → Validated).** (Definition → Implemented →
> Validated; see [README.md](README.md).) Pairs with [../CHARTER.md](../CHARTER.md)
> (scope + invariants), [../ROADMAP.md](../ROADMAP.md) (M2 "soak/fuzz on real radios"),
> and [../IMPLEMENTATION_PLAN.md](../IMPLEMENTATION_PLAN.md) (Track A.3). Change
> deliberately; code docstrings cite this spec's `§` numbers.

**Milestone / Initiative:** M2  **Track:** A.3  **Author:** agent-authored under
`openspec/changes/gcp-drone-m2-agent-hardening`, maintainer-reviewed / 2026-07-24

---

## 1. Scope

Link-layer denial (802.11-class deauthentication, jamming, radio dropout) is an
**availability** attack. TLS and endpoint auth — the rest of M2 — do not address it;
an auth control must never be accepted as mitigation for an availability gap. What
must hold when the link dies mid-stream, in priority order:

1. **Fail closed:** the heartbeat-driven pre-arm interlock (`meshsa.command.health.
   HeartbeatHealth`) denies arming the moment heartbeats go stale and stays denied for
   the whole outage; the Jetson `LANDING_TARGET` bridge suppresses publishes the same
   way (`jetson_yolo_gcs.mavlink.bridge`, already shipped — this soak generalizes its
   pattern to the command side).
2. **No retry storm:** reconnect supervisors (`meshsa.transports.backoff.Backoff`)
   saturate at their configured cap — the attempt rate is bounded by `1/max_s`; the
   send pacer (`meshsa.transports.pacing.Pacer`) caps the post-reconnect backlog flush
   at its sustained rate.
3. **Clean recovery:** one fresh heartbeat restores arm permission; `Backoff.reset()`
   returns the schedule to `initial_s`.

Deliverable: the deterministic soak/fuzz suite
`packages/meshsa/tests/test_link_loss_soak.py` (per-PR cycles + `slow`-marked nightly
fuzz), plus the §8 bench checklist for on-radio validation.

### Non-goals (explicitly deferred)

- **MAVLink 2 signing research** — belongs to the `TransportAuthPolicy` seam
  (`meshsa.netauth`); a signing implementation is a separate, gated change.
- **On-radio automation in CI** — §8 bench runs are manual until a radio-equipped
  runner exists (the `fts-e2e` workflow precedent).
- Any commanding enablement (CHARTER carve-out gate unchanged).

---

## 2. Facts the implementation relies on

- 802.11 deauthentication is unauthenticated in pre-802.11w networks; a link can drop
  with **zero warning** at any point in a stream. The soak therefore cuts the link
  between arbitrary events, not at friendly boundaries.
- `HeartbeatHealth` freshness is measured on an injected monotonic `Clock`
  (`meshsa.protocols.Clock`); wall-clock steps must not open the gate.
- `Pacer` and `Backoff` take injected clock/sleep seams (`SleepFn`), so thousands of
  simulated link cycles run in milliseconds with no real waiting.

---

## 3. Architecture

No new runtime components. The soak drives the three existing seams with a manually
stepped fake clock and a recording sleep:

```
ManualClock ──> HeartbeatHealth ──(HealthReport.arm_permitted)──> assert fail-closed
      │  └────> Pacer.acquire  ──(recorded delays)─────────────> assert rate ≤ cap
      └───────> Backoff.sleep_and_advance ─(recorded delays)───> assert saturation
```

Everything is reached with fakes (CHARTER §4.3); no hardware, no sockets.

---

## 4. Behaviour / state model

Normative assertions, soaked over hundreds of randomized link cycles:

- **Interlock:** `arm_permitted` is `False` before the first beat, `False` for any
  silence `> max_age_s` (regardless of outage length), `True` again after one fresh
  beat. Reasons carry `heartbeat_stale` during the outage. "Healthy" never silently
  means "stale but recently healthy".
- **Pacer:** over any flood of `n` sends, simulated elapsed time ≥
  `(n - burst) / rate_hz`; no single wait exceeds one token interval; a clock stall
  refills at most `burst` tokens; a backward clock jump never produces a spurious
  sleep or burst.
- **Backoff:** delays grow `initial → min(current·factor, max)` and hold at `max_s`;
  no recorded delay ever exceeds `max_s`; `reset()` restores `initial_s`.

---

## 5. Module specifications

No new runtime modules or config fields. The soak's operational values are named
constants in the test module (cycle counts, the FTS-facing pacer profile, the
TAK/Meshtastic-shaped backoff schedule) — test parameters, not deployed config. The
runtime values they mirror remain config fields of their owning modules
(`TransportConfig.options` pacing, transport backoff settings, commander
`arm_report_max_age_s`).

---

## 6. Wire / schema posture (backward compatibility)

**N/A** — no wire change.

---

## 7. Test plan (by category)

Coverage floor: the exercised modules (`pacing`, `backoff`, `command/health`) stay at
100% (they already are; the package gate is ≥97%).

- **Unit/soak** — `test_link_loss_soak.py`: 500-cycle interlock soak, flood/stall/
  backward-jump pacer soaks, 500-step backoff saturation.
- **Fuzz (nightly, `slow`)** — 5 000 randomized outage/recovery cycles (fixed seed),
  asserting the gate and schedule never wedge.
- **Security** — fail-closed assertions run against the real logic; mocking the
  decision predicates is forbidden (test-engineer roster rule).

---

## 8. Exit criteria

- **Mechanism (binary, met):** §7 green in per-PR CI; nightly fuzz green; gates
  (`ruff`/`ruff format`/`mypy`/`pytest` + coverage) green.
- **Validation (pending → Validated):** on the bench HaLow/ELRS link — (a) forced
  deauth/power-cut mid-stream: commander refuses arm within `max_age_s`, Jetson
  suppresses `LANDING_TARGET`; (b) reconnect: no send burst above the configured
  pacer rate on flush; (c) sustained 1 h flap soak: no unbounded retry logging, no
  queue growth. Record evidence under `ops/` per repo convention.

---

## 9. CHARTER §4 invariant checklist

| # | Invariant | How this design preserves it |
|---|-----------|------------------------------|
| 1 | Open/closed registry extensibility | no registry change; soak drives existing seams |
| 2 | Versioned, backward-compatible wire | §6 N/A — no wire change |
| 3 | DI via `Protocol`, tests need no hardware | injected `Clock`/`SleepFn` fakes throughout |
| 4 | Stateful I/O in transports/services, not codecs | no I/O added; assertions only |
| 5 | Config-driven, no magic numbers | soak constants documented in-module; runtime values stay config fields |
| 6 | Quality gates green | soak runs inside the per-PR gate; fuzz in nightly |
| 7 | No secrets / machine fingerprints in repo | none introduced |
