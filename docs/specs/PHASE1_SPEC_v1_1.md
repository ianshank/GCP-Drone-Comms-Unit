# Phase 1 Specification v1.1 — Telemetry Ingest, Link Health & Flight Logger

> Committed to the repo for traceability: implemented by the `meshsa.fpv` subsystem.
> Section references (`§5.1`, `§4.2`, …) in code docstrings and the implementation
> plan point here. See [docs/ARCHITECTURE.md](../ARCHITECTURE.md#fpv-ground-side-telemetry-subsystem).

**Status**: Definition (pre-implementation). Gated on Phase 0 exit criteria
**plus Phase 0 Errata E1 (half-duplex wiring + echo suppression)**.
**Builds on**: `fpv_ground` v0.1.1 (= v0.1.0 + Errata E1.2/E1.3 echo handling).

-----

## 1. Scope

Deliverables, priority order:

1. **Telemetry parsing** — typed decoding of CRSF telemetry frames from the
   ELRS TX module’s handset-side UART.
2. **Link-health monitor** — LQ/RSSI/staleness evaluation with a deliberately
   limited authority model (§4) and an enforcement point (§5.6).
3. **Flight logger** — synchronized RC + telemetry + video + events per
   session; the dataset contract for Phase 3.
4. **`fpv_ground` v0.1.1** — Errata E1.2/E1.3 echo suppression in `CrsfLink`
   and the prober.

### Non-goals (explicitly deferred)

- Any in-flight modification of RC output based on telemetry (no auto-RTH,
  auto-land, throttle intervention, or **auto-disarm** — see §4.1 and §5.6).
- GPS payload parsing beyond raw capture.
- Vision/tracking (Phase 2). MSP/Path-B telemetry.

-----

## 2. Protocol facts the implementation relies on

### 2.0 Electrical interface

Single-wire half-duplex (Errata E1.1). Two load-bearing consequences: **echo**
(every transmitted frame is also received → suppressed in `poll_inbound`, E1.2)
and **master/slave timing** (the module replies in gaps; 100 Hz leaves ~10 ms
gaps, ample; bench item #4 confirms CRC error rate, `tx_gap_us` is the remedy).

### 2.1 Endianness

CRSF telemetry payloads are **big-endian** (`struct.unpack('>...')`). RC bit
packing is little-endian bit order. Golden-vector tests must fail under
little-endian decode (§6).

### 2.2 Frame payload layouts

**0x14 LINK_STATISTICS — 10 bytes** (primary health signal): u8 uplink_rssi_ant1
(dBm×−1), u8 uplink_rssi_ant2, u8 uplink_lq (%), i8 uplink_snr, u8 active_antenna,
u8 rf_mode (enum drifts across ELRS majors, §4.3), u8 uplink_tx_power
(enum {0,10,25,100,500,1000,2000,250,50} mW), u8 downlink_rssi (dBm×−1), u8
downlink_lq (%), i8 downlink_snr.

**0x08 BATTERY_SENSOR — 8 bytes** (requires FC telemetry): u16 voltage, u16
current, u24 fuel_drawn (mAh), u8 remaining (%). Scale is a Settings value
(bench item #1).

**0x1E ATTITUDE — 6 bytes**: i16 pitch, i16 roll, i16 yaw — rad × 10000.

**0x21 FLIGHT_MODE**: null-terminated ASCII; `"!FS!"` = failsafe → loggable
safety event.

**0x10/0x3A sync/radio-ID**: parse-and-ignore at debug; never “unknown”.

### 2.3 ELRS cadence

Downlink telemetry bandwidth follows the configured telemetry ratio (1:2…1:128).
Staleness thresholds are set from the measured ratio sweep (bench item #3), not
constants. LINK_STATISTICS delivery is near-continuous (but see §4.2).

-----

## 3. Architecture

```
CrsfLink.poll_inbound()  ── echo-suppressed frames (v0.1.1)
        │
TelemetryParser.parse()  ── pure; typed dataclass | None      (§5.1)
        │
TelemetryStore.update()  ── latest + bounded history ring     (§5.2)
        │                         │
LinkHealthMonitor        FlightLogger (writer thread)         (§5.3, §5.4)
        │
AlertSink (console/log; pluggable)        ArmGuard wraps RCLink (§5.6)
```

All components: Protocol seams, Settings-driven, injected clocks, testable
without hardware. Single asyncio consumer owns store + monitor; the logger is
the only component with its own thread (§5.4.3).

-----

## 4. Link-health model

### 4.1 Authority rule (normative)

The monitor never commands the aircraft in flight. Software auto-disarm on
degraded LQ converts a degrading link into a guaranteed crash; degraded-link
authority lives where it belongs (ELRS RF failsafe → Betaflight
`failsafe_procedure`). The monitor’s two powers: **arm gating** (pre-flight,
enforced by §5.6) and **advisory alerts** (in flight, operator decides).

### 4.2 Co-signal evaluation (replaces naive freshness)

Uplink LQ is measured at the receiver and returns via the downlink: the metric’s
freshness degrades exactly when the link does. Rules:

1. `LinkStats` age > `health_linkstats_stale_s` ⇒ state ≥ WARN regardless of the
   stale frame’s contents; > `2×` ⇒ CRITICAL. **Stale can never be OK.**
2. Uplink LQ thresholds apply only to fresh frames.
3. Downlink LQ trending down is an early-warning co-signal: raises WARN at
   `health_downlink_lq_warn` even while uplink reads clean.
4. Reason codes: `lq_below_warn`, `lq_below_critical`, `linkstats_stale`,
   `downlink_degrading`, `no_telemetry`.

### 4.3 Thresholds (Settings; provisional until §8 calibration)

`health_lq_warn`/`health_lq_critical` = 70/50 %; `health_downlink_lq_warn` = 60 %;
`health_rssi_margin_db` = 10 dB above sensitivity floor; `health_linkstats_stale_s`
= 1.0 s; `health_fc_telemetry_stale_s` = 5.0 s; `health_hysteresis_s` = 2.0 s
(anti-flap on upgrade transitions). Sensitivity floors are a map keyed by
`(elrs_major_version, rf_mode)` in Settings.

State machine: `NO_DATA → OK → WARN → CRITICAL`, hysteresis on recovery only
(degradation immediate). Every transition is an event.

-----

## 5. Module specifications

### 5.1 `crsf/telemetry.py` — pure parsers

Frozen dataclasses `LinkStatistics`, `BatterySensor`, `Attitude`,
`FlightMode(is_failsafe)`; union `TelemetryMessage`.
`TelemetryParser.parse(frame) -> TelemetryMessage | None`: big-endian only;
payload length validated per type before unpack; RSSI negation and unit scaling
here and nowhere else; `telemetry_voltage_scale`/`telemetry_current_scale` from
Settings (default 0.1). Unknown types: None + per-type counter, never an
exception. Malformed known types: `TelemetryParseError`.

### 5.2 `telemetry_store.py`

`update(msg, t_mono)`, `latest(type)`, `age_s(type, now)`, `history(type, n)`.
Ring `store_history_len` (512). No I/O, no threads.

### 5.3 `link_health.py`

`HealthState{NO_DATA,OK,WARN,CRITICAL}`;
`HealthReport(state, arm_permitted, reasons, t_mono)`.
`LinkHealthMonitor(settings, store, sink, clock).evaluate()`, pure given
store+clock, called ≥ 2 Hz. `arm_permitted = (state is OK)`.
`AlertSink.alert(report, previous)` Protocol; console implementation ships.

### 5.4 `flight_logger.py`

#### 5.4.1 Session contract

`sessions/<UTC-ISO>-<shortid>/`. `manifest.json`: wall-clock start, settings
snapshot, git SHA, package version, hardware notes, **`schema_version` (int,
starts at 1)**, **`capture_latency_ms`** (null until measured), **wiring option
(E1.1 A/B)**, observed per-type telemetry rates. Every JSONL file’s first line is
a header record `{"schema_version": 1, "file": "rc", "fields": [...]}`.

Files: `rc.jsonl` `{t, ch}`; `telemetry.jsonl` `{t, type, fields...}`;
`events.jsonl` (arm/disarm, health transitions, `!FS!`, notes); `video.mp4` +
`frames.jsonl` `{t, frame_idx}` (camera wired in Phase 2).

#### 5.4.2 Time semantics

`time.monotonic()` is the only intra-session timebase; wall clock appears once,
in the manifest. `frames.jsonl` `t` is capture-read time; Phase 3 shifts video by
`−capture_latency_ms`.

#### 5.4.3 Concurrency

One **writer thread** owns all file handles. `record_rc/telemetry/event` are
non-blocking enqueues onto a bounded queue (`logger_queue_len`, 4096). Overflow:
`rc`/`telemetry` dropped-and-counted (`dropped_records` per stream, in manifest);
`event` records block the caller up to `logger_event_timeout_s` (0.5) and raise on
failure — events never silently lost. Writer flushes every `flush_every_s` (1.0).
JSONL chosen so a truncated final line is recoverable. `close()` idempotent,
drains, joins; context-manager. Post-session `fpv-log-convert` → Parquet.

### 5.5 Tools

- **`fpv-telemetry-monitor`** — streams idle RC, prints parsed telemetry + health
  + echo/CRC counters; `--record` exercises the logger.
- **`fpv-log-replay`** — replays `telemetry.jsonl` through store + monitor; asserts
  health outcomes under candidate thresholds.
- **`fpv-log-convert`** — JSONL → Parquet (schema_version-aware).

### 5.6 `arm_guard.py` (enforcement, not convention)

`ArmGuard` wraps any `RCLink` (decorator; satisfies `RCLink`):

- **Gates the low→high transition only.** A send raising the arm channel above
  `arm_threshold_us` is permitted iff the most recent `HealthReport` is fresher
  than `arm_guard_report_max_age_s` (1.0) and `arm_permitted` is True; otherwise
  the arm channel is clamped low, the send otherwise passes through, and an
  `arm_blocked` event is emitted.
- **Latch — never disarms.** Once an armed frame has passed, the guard latches and
  applies no further clamping until it observes the arm channel commanded low by
  the caller. Degraded health in flight produces alerts, never intervention.

-----

## 6. Test plan (summary)

Parsers: golden vectors per type; little-endian decode of multi-byte vectors
asserts a wrong value; RSSI negation; truncated payload raises; unknown → None +
counter; `!FS!` flag; configurable scales. Echo (v0.1.1): scripted echoing
transport; prober margin. Store: latest/age/history with FakeClock; ring bound;
type isolation. Health: every transition; recovery hysteresis vs immediate
degradation; stale-cannot-be-OK; downlink-degrading; version-keyed floor; arm
gating reasons. ArmGuard: blocks/passes/latch/re-arm/non-arm passthrough. Logger:
overflow drop-and-count, events block-then-raise, header line present, mid-write
close recovery, idempotent close, replay roundtrip. Integration: mixed scripted
stream end-to-end. Coverage: ≥95% new modules; parsers, health, ArmGuard at 100%.

-----

## 8. Exit criteria

Mechanism validation (binary): §6 green incl. echo + ArmGuard suites; live
LinkStats on hardware with echoes suppressed; voltage within 0.2 V of multimeter;
antenna-removal transitions + hysteresis + ArmGuard blocks re-arm while degraded;
one logged session → Parquet → replay with identical health outcomes; manifest
carries schema_version, capture_latency_ms, wiring, drop counters.

Threshold calibration (explicitly separate — values remain provisional after
mechanism validation): LQ warn/critical and staleness from the ratio sweep + at
least one replayed degradation recording.
