# Phase 0 Errata — E1 (Hardware Interface Correction)

> Committed to the repo for traceability: the `meshsa.fpv` subsystem implements this
> errata. See [docs/ARCHITECTURE.md](../ARCHITECTURE.md#fpv-ground-side-telemetry-subsystem)
> for how it maps onto the code.

Applies to `fpv_ground` v0.1.0 and AGENTS.md v3 Step 9. **Blocking for the
Phase 0 hardware runbook steps 2–4 and all of Phase 1.**

-----

## E1.1 — Wiring table was transmit-only (CRITICAL)

The JR-bay CRSF pin is a **single-wire half-duplex** line. The v3/Phase 0
wiring table connected only FTDI TX → CRSF pin + GND, leaving no receive path:
module telemetry replies were electrically unreceivable. Consequences as
shipped: the address-prober’s auto-detection can never see telemetry, and
Phase 1 ingest would starve.

### Corrected wiring (Option A — resistor tie, standard DIY half-duplex)

|Connection                                   |Detail                                             |
|---------------------------------------------|---------------------------------------------------|
|FTDI TX → series resistor (~1 kΩ) → CRSF line|resistor lets the module win the line when replying|
|FTDI RX → CRSF line (direct)                 |receive path — this was missing                    |
|FTDI GND → module GND                        |unchanged                                          |
|Module VCC                                   |per module spec, unchanged                         |

Option B: a purpose-built half-duplex/one-wire UART adapter. Either is
acceptable; record which in the session manifest (`wiring` field).

### New bench step 0 (before the address prober)

With corrected wiring and **no frames being sent**, run a raw read for 10 s:
a powered module may emit periodic sync/device frames; any valid inbound frame
proves the receive path. If silent, proceed to the prober — but a prober
failure now distinguishes “wrong address” from “no RX path” only after this
step has passed once during a transmit session.

## E1.2 — Echo contamination (CRITICAL, discovered via E1.1)

With TX and RX tied to one line, **we receive our own transmitted frames**.
Unfiltered, every echoed RC_CHANNELS_PACKED frame is CRC-valid inbound data,
which means the v0.1.0 address-prober would count echoes as “telemetry” and
report a confident winner for *every* candidate address — a false positive
that defeats the tool’s purpose.

### Required change to `CrsfLink.poll_inbound()` (fpv_ground v0.1.1)

Suppress self-echo before returning frames:

1. Drop any inbound frame where `frame.type == RC_CHANNELS_PACKED` and
   `frame.addr == self.address` (we are the only RC source on this line), and
2. (belt-and-braces) maintain a short deque of recently transmitted frame
   bytes; drop exact matches.

Expose `echoes_suppressed` as a counter (debug log + prober output). The
prober’s telemetry count must exclude suppressed echoes; add a regression
test: scripted transport that echoes every write **plus** responds with
telemetry only for the correct address → prober must still pick only the
correct address, and must report zero telemetry for wrong addresses.

> **Implementation note (`meshsa.fpv`):** on a single-wire line an echo is
> bitwise-identical to what was written, so rule (2) (exact-byte match) is the
> *primary, reliable* filter and rule (1) is the spec-mandated secondary; the
> link addresses transmitted RC frames with its own `crsf_address` so rule (1)
> still fires after the dedupe deque rolls over.

## E1.3 — Prober pass criteria tightened

`probe_min_telemetry_frames` now counts only **non-echo, non-RC** frame types
(LINK_STATISTICS, sync/device frames). Result confidence additionally requires
the winning address’s count to exceed the runner-up by a configurable factor
(`probe_margin`, default 3×) to guard against residual echo artifacts.

-----

Status: E1.1 is a documentation + bench-procedure fix. E1.2/E1.3 are code
changes scheduled as `fpv_ground` v0.1.1, to be implemented alongside Phase 1
(same `CrsfLink` file, one release). Phase 0 test suite gains the echo
regression tests; all existing tests remain valid.
