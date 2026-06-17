# Betaflight FC: GPS-less telemetry track + pilot-from-Jetson (MSP RC)

Builds on the existing `meshsa`/`flightctl` stack to make a **real Betaflight flight
controller over USB** a first-class citizen — both as a TAK track and as something the Jetson
can pilot — without any `Envelope`/schema change. Two additive feature sets (0.4.0 + 0.5.0),
verified on hardware (a Mobula7 1S, BTFL 4.4.2, STM32F411 / `CRAZYBEEF4SX1280`).

## 0.4.0 — MSP telemetry for a GPS-less bench FC
- **Fixed-position fallback** in `msp_source` (`fallback_lat`/`lon`/`hae`): a GPS-less FC still
  appears as a track; a real GPS fix always wins; no fix + no fallback = nothing (unchanged).
- **Telemetry remarks**: the MSP poll also reads battery voltage / current / RSSI (`MSP_ANALOG`)
  and attitude (`MSP_ATTITUDE`); present fields render into an optional `payload["remarks"]` that
  the `telemetry` and `cot` codecs carry through to the CoT `<detail><remarks>` element. Optional,
  additive — **no schema bump** (`payload` is unstructured).
- **Ops**: `FC_MODE=msp` in `start_all.sh` + `configs/jetson_gateway.msp.json` (polls the FC
  directly, skips the MAVLink chain). Stable `/dev/flightctl-fc` via the udev rule.

## 0.5.0 — pilot the FC from the Jetson (MSP RC), HITL-ready
- **`meshsa.rc`** (tested, hardware-free): Linux joystick parsing, stick/switch→RC mapping
  (`AxisChannel`/`ButtonChannel`/`ButtonGroupChannel`, axis- or button-sourced ARM), an
  arm/failsafe state machine, and a fixed-rate `MspPilot` loop — all behind a pluggable
  **`ChannelSource`** so the joystick is just the first input (sim/autonomy drop in later).
- **`flightctl/rc_bridge.py`** daemon + **`FC_MODE=pilot`**: owns the one exclusive FC serial,
  streams `MSP_SET_RAW_RC` from `/dev/input/js0`, and decimates the same handle (`RoundRobinTelemetry`,
  one MSP read per call) to also publish the CoT track — so you pilot *and* see the track at once.
  `--dry-run` (calibrate, no FC writes) and `--monitor` (MSP_RC read-back) for safe bring-up.

## Safety (this drives motors)
Starts **disarmed / throttle-min**, **never auto-arms** (arm switch must be seen released first),
**fails safe** (disarm + throttle-min) on stale input, requires the arm switch to be **re-cycled
after any failsafe**, and **disarms on shutdown**. All bench/HITL — USB-tethered, not for flight.

## Verified on hardware
- Live MSP telemetry: real poll → fallback track + live attitude remarks, decoded end-to-end.
- Radio calibrated (RadioMaster Pocket/EdgeTX): gimbals axes 0-3 (throttle axis 2), switches as
  axes, ARM = axis 7.
- FC switched to **MSP RX** over MSP (`RX_SPI`→`RX_MSP`, saved); FC `MSP_RC` read-back confirmed
  correct **Betaflight AETR** channel order with `armingDisableFlags=0` (armable).
- **Held before motor spin**: the props-off arm test is the one remaining bench step (see NEXTSTEPS).

## Quality
- **Full suite, 100% line+branch coverage**; `mypy --strict` + `ruff`/`ruff format` clean; wheel/sdist build.
- New integration/e2e/regression suites (no hardware): MSP fix/fallback/remarks → CoT air track
  through `build_node`; the shipped configs build and honour the AETR channel order (pins the
  throttle/yaw bug caught on the bench); full pilot arm/failsafe lifecycle through the loop;
  round-robin telemetry → CoT XML. Hardware/serial/joystick glue is the only `# pragma: no cover`.

## Reversibility (ELRS handoff)
Switching to MSP RX is reversible for ELRS: `feature -RX_MSP` + **`feature RX_SPI`** + `save`
(this board's ELRS is SPI, not serial). The Jetson then reverts to `FC_MODE=msp` telemetry.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
