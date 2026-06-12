"""End-to-end: link -> parser -> store -> monitor -> logger (+ ArmGuard).

Drives a mixed scripted stream (LinkStatistics / battery / attitude / garbage /
CRC error / RC echoes) through the whole stack and asserts the dataset and the
counters, then exercises the ArmGuard gate against live health.
"""

from __future__ import annotations

import json
import os

from _fpv_helpers import (
    FakeCrsfSerial,
    ManualClock,
    attitude_bytes,
    battery_bytes,
    link_statistics_bytes,
)

from meshsa.fpv.arm_guard import ArmGuard
from meshsa.fpv.config import (
    ArmGuardSettings,
    CrsfLinkSettings,
    HealthSettings,
    LoggerSettings,
    ParserSettings,
)
from meshsa.fpv.crsf.link import CrsfLink
from meshsa.fpv.crsf.telemetry import Attitude, BatterySensor, LinkStatistics, TelemetryParser
from meshsa.fpv.flight_logger import FlightLogger
from meshsa.fpv.link_health import ConsoleAlertSink, HealthState, LinkHealthMonitor
from meshsa.fpv.telemetry_store import TelemetryStore
from meshsa.fpv.tools.monitor import pump_once


class _RecordingRCLink:
    def __init__(self) -> None:
        self.sent: list[list[int]] = []

    def send_rc(self, channels) -> None:
        self.sent.append(list(channels))


def test_end_to_end_stream_and_manifest(tmp_path):
    fake = FakeCrsfSerial(echo=True)
    link = CrsfLink(CrsfLinkSettings(crsf_address=0xC8), serial=fake)
    link.open()
    clock = ManualClock()
    parser = TelemetryParser(ParserSettings())
    store = TelemetryStore()
    monitor = LinkHealthMonitor(HealthSettings(), store, clock, ConsoleAlertSink())
    logger = FlightLogger(
        LoggerSettings(sessions_root=str(tmp_path)),
        clock=clock,
        git_sha=None,
        now_utc="2026-06-12T00:00:00+00:00",
        session_id="e2e",
    )
    logger.start()

    # A messy line: our RC echoes, real telemetry, leading garbage, a CRC-bad frame.
    corrupt = bytearray(link_statistics_bytes(addr=0xEA))
    corrupt[-1] ^= 0xFF
    link.send_rc([1500, 1500, 1500, 1500, 1000, 1500])  # echoed back (suppressed)
    fake.feed(b"\x11\x22\x33")  # garbage (resynced past)
    fake.feed(link_statistics_bytes(addr=0xEA, uplink_lq=100))
    fake.feed(bytes(corrupt))  # CRC error (counted, dropped)
    fake.feed(battery_bytes(addr=0xC8))
    fake.feed(attitude_bytes(addr=0xC8))
    link.send_rc([1600, 1500, 1500, 1500, 1000, 1500])  # another echo

    for _ in range(3):
        pump_once(link, parser, store, monitor, clock, logger=logger)
        clock.advance(0.01)

    # Persist link counters into the manifest, then close.
    logger.set_note("echoes_suppressed", link.echoes_suppressed)
    logger.set_note("crc_errors", link.crc_errors)
    logger.close()

    # All three telemetry types reached the store.
    assert store.latest(LinkStatistics) is not None
    assert store.latest(BatterySensor) is not None
    assert store.latest(Attitude) is not None
    # Echoes suppressed and the corrupt frame counted.
    assert link.echoes_suppressed == 2
    assert link.crc_errors == 1

    with open(os.path.join(logger.session_dir, "telemetry.jsonl")) as fh:
        tel = [json.loads(line) for line in fh if line.strip()]
    types = {r["type"] for r in tel[1:]}
    assert {"LinkStatistics", "BatterySensor", "Attitude"} <= types

    with open(os.path.join(logger.session_dir, "manifest.json")) as fh:
        manifest = json.loads(fh.read())
    assert manifest["notes"]["echoes_suppressed"] == 2
    assert manifest["notes"]["crc_errors"] == 1
    assert manifest["dropped_records"] == {"rc": 0, "telemetry": 0}


def test_armguard_gate_against_live_health():
    clock = ManualClock()
    store = TelemetryStore()
    monitor = LinkHealthMonitor(HealthSettings(), store, clock)
    raw_link = _RecordingRCLink()
    guard = ArmGuard(raw_link, ArmGuardSettings(), clock)

    def good_ls() -> LinkStatistics:
        return LinkStatistics(-50, -50, 100, 8, 0, 0, 100, -50, 100, 8)

    # Drive health to OK (acquisition + hysteresis), feeding the guard each cycle.
    store.update(good_ls(), clock.now())
    guard.update_health(monitor.evaluate())  # NO_DATA
    guard.send_rc([1500, 1500, 1500, 1500, 2000, 1500])
    assert raw_link.sent[-1][4] == ArmGuardSettings().arm_clamp_us  # blocked (not OK yet)

    clock.advance(HealthSettings().health_hysteresis_s)
    store.update(good_ls(), clock.now())
    report = monitor.evaluate()
    assert report.state is HealthState.OK
    guard.update_health(report)
    guard.send_rc([1500, 1500, 1500, 1500, 2000, 1500])
    assert raw_link.sent[-1][4] == 2000  # armed once health is fresh-OK
    assert guard.latched is True
