"""FPV subsystem configuration.

Mirrors :mod:`meshsa.config`: every operational value is a pydantic field with an
explicit, overridable default — there are no magic numbers buried in the code.
``FpvSettings`` composes grouped sub-models and loads from a mapping, a JSON
file, or the environment (``MESHSA_FPV_`` prefix), exactly like ``NodeConfig``.

CRSF *protocol* constants (sync/address byte semantics, CRC polynomial, frame
type IDs, the 11-bit RC channel width) are fixed by the wire spec and live in
:mod:`meshsa.fpv.crsf.frame`, not here — those are not deployment tunables.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, Field


class ParserSettings(BaseModel):
    """Unit scaling and markers applied by the telemetry parser (§5.1)."""

    #: BATTERY_SENSOR voltage scale; firmware-dependent (mV*100 vs 0.1 V) — bench item #1.
    telemetry_voltage_scale: float = 0.1
    #: BATTERY_SENSOR current scale; same firmware ambiguity as voltage.
    telemetry_current_scale: float = 0.1
    #: ATTITUDE fields are transmitted as radians * 10000.
    attitude_rad_scale: float = 1e-4
    #: FLIGHT_MODE substring that marks an RF failsafe (loggable safety event).
    failsafe_marker: str = "!FS!"


class HealthSettings(BaseModel):
    """Link-health thresholds (§4.3). Provisional until bench calibration (§8)."""

    health_lq_warn: int = 70
    health_lq_critical: int = 50
    health_downlink_lq_warn: int = 60
    health_rssi_margin_db: int = 10
    health_linkstats_stale_s: float = 1.0
    health_fc_telemetry_stale_s: float = 5.0
    health_hysteresis_s: float = 2.0
    #: Installed ELRS major version; selects the version-keyed sensitivity floor
    #: (the rf_mode index is remapped across majors — a version-blind lookup picks
    #: the wrong floor). Set per installed firmware (bench item #2).
    elrs_major_version: int = 3
    #: Receiver sensitivity floors (dBm) keyed ``"<elrs_major>:<rf_mode>"``. A
    #: string key keeps the map JSON/env-safe; the rf_mode index is remapped
    #: across ELRS majors, so the floor must be selected version-aware. Ships an
    #: ELRS-3.x baseline; verify/populate per installed firmware (bench item #2).
    sensitivity_floors: dict[str, int] = Field(
        default_factory=lambda: {
            "3:0": -120,
            "3:1": -117,
            "3:2": -112,
            "3:3": -108,
            "3:4": -105,
            "3:5": -105,
            "3:6": -105,
        }
    )

    def sensitivity_floor(self, elrs_major: int, rf_mode: int) -> int | None:
        """Return the sensitivity floor for ``(elrs_major, rf_mode)`` or None."""
        return self.sensitivity_floors.get(f"{elrs_major}:{rf_mode}")


class LoggerSettings(BaseModel):
    """Flight-logger queue, flush, and session-layout settings (§5.4)."""

    logger_queue_len: int = 4096
    logger_event_timeout_s: float = 0.5
    #: Upper bound on shutdown: the sentinel enqueue and the writer-thread join in
    #: ``close()`` each wait at most this long, so a wedged writer (e.g. a stuck
    #: disk) can never hang the caller indefinitely.
    logger_shutdown_timeout_s: float = 2.0
    flush_every_s: float = 1.0
    sessions_root: str = "sessions"
    #: Telemetry history ring length; also consumed by ``TelemetryStore`` (§5.2).
    store_history_len: int = 512
    #: Recorded in the manifest (E1.1). Non-behavioral provenance of the wiring used.
    wiring: str = "half_duplex_tied"


class ArmGuardSettings(BaseModel):
    """Pre-flight arm-gating settings (§5.6)."""

    arm_channel_index: int = 4
    arm_threshold_us: int = 1500
    arm_guard_report_max_age_s: float = 1.0
    #: Value the arm channel is clamped to while gating (disarmed low).
    arm_clamp_us: int = 1000


class CrsfLinkSettings(BaseModel):
    """Half-duplex CRSF serial-link settings (E1.2/E1.3, §2.0)."""

    crsf_device: str = "/dev/ttyAMA0"
    #: Single-wire half-duplex handset line runs at 400 kbaud (spec §2.0). The
    #: full-duplex FC side uses 416666; set per deployment if wired differently.
    crsf_baud: int = 400000
    #: Our device address (CRSF_ADDRESS_RADIO_TRANSMITTER = 0xEA, the handset).
    crsf_address: int = 0xEA
    #: Depth of the recently-transmitted-frame deque used for exact-match echo
    #: suppression — the reliable echo filter on a single-wire line (E1.2 rule B).
    echo_dedupe_len: int = 16
    #: Maximum CRSF frame length in bytes (sync+len+type+payload+crc) used to
    #: bound the accumulator and reject corrupt length fields.
    crsf_max_frame_len: int = 64
    #: Inbound frame queue bound; overflow is dropped-and-counted.
    crsf_queue_len: int = 1000
    #: Bytes to request per non-blocking serial read in ``poll_inbound``.
    crsf_read_chunk: int = 256
    #: RC frame channel count and the microsecond<->11-bit-tick linear mapping
    #: endpoints (TBS/CRSF default: 988us->172, 2012us->1811). Configurable so a
    #: non-standard handset range never needs a code change.
    rc_channel_count: int = 16
    rc_us_min: int = 988
    rc_us_max: int = 2012
    rc_ticks_min: int = 172
    rc_ticks_max: int = 1811


class ProberSettings(BaseModel):
    """Address-prober pass criteria (E1.3)."""

    probe_min_telemetry_frames: int = 5
    #: Winner must exceed runner-up by this factor to guard against echo artifacts.
    probe_margin: float = 3.0
    probe_duration_s: float = 2.0
    #: Candidate addresses to probe (flight-controller, receiver, transmitter, …).
    probe_addresses: list[int] = Field(default_factory=lambda: [0xC8, 0xEC, 0xEE, 0xEA])


class FpvSettings(BaseModel):
    """Root FPV settings; compose-and-default, no magic numbers in code."""

    parser: ParserSettings = Field(default_factory=ParserSettings)
    health: HealthSettings = Field(default_factory=HealthSettings)
    logger: LoggerSettings = Field(default_factory=LoggerSettings)
    arm_guard: ArmGuardSettings = Field(default_factory=ArmGuardSettings)
    crsf: CrsfLinkSettings = Field(default_factory=CrsfLinkSettings)
    prober: ProberSettings = Field(default_factory=ProberSettings)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> FpvSettings:
        """Build settings from a dict-like mapping (validation + coercion)."""
        return cls.model_validate(dict(data))

    @classmethod
    def from_file(cls, path: str) -> FpvSettings:
        """Build settings from a JSON file."""
        with open(path, encoding="utf-8") as fh:
            return cls.from_mapping(json.load(fh))

    @classmethod
    def from_env(
        cls, environ: Mapping[str, str] | None = None, prefix: str = "MESHSA_FPV_"
    ) -> FpvSettings:
        """Build settings from the environment.

        A ``<prefix>CONFIG_JSON`` blob is merged first (full nested override),
        then ``<prefix>SESSIONS_ROOT`` applies a convenience scalar override for
        the most commonly tuned deployment value.
        """
        env = dict(os.environ if environ is None else environ)
        data: dict[str, Any] = {}
        blob = env.get(f"{prefix}CONFIG_JSON")
        if blob:
            data.update(json.loads(blob))
        sessions_root = env.get(f"{prefix}SESSIONS_ROOT")
        if sessions_root:
            logger = dict(data.get("logger", {}))
            logger["sessions_root"] = sessions_root
            data["logger"] = logger
        return cls.model_validate(data)
