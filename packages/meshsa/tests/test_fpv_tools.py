"""fpv-telemetry-monitor pure cores: arg parsing, settings build, pump_once."""

from __future__ import annotations

import json

from _fpv_helpers import FakeCrsfSerial, ManualClock, link_statistics_bytes

from meshsa.fpv.config import CrsfLinkSettings, FpvSettings, HealthSettings
from meshsa.fpv.crsf.link import CrsfLink
from meshsa.fpv.crsf.telemetry import TelemetryParser
from meshsa.fpv.link_health import HealthState, LinkHealthMonitor
from meshsa.fpv.telemetry_store import TelemetryStore
from meshsa.fpv.tools.monitor import build_settings, parse_args, pump_once


def test_parse_args_defaults_and_overrides():
    args = parse_args([])
    assert args.record is False
    assert args.log_level == "INFO"
    args = parse_args(["--device", "/dev/ttyUSB0", "--baud", "420000", "--record"])
    assert args.device == "/dev/ttyUSB0"
    assert args.baud == 420000
    assert args.record is True


def test_build_settings_applies_cli_overrides(tmp_path):
    cfg = tmp_path / "fpv.json"
    cfg.write_text(json.dumps({"crsf": {"crsf_baud": 400000}}))
    args = parse_args(
        [
            "--config",
            str(cfg),
            "--device",
            "/dev/ttyAMA0",
            "--baud",
            "420000",
            "--sessions-root",
            "/data",
        ]
    )
    settings = build_settings(args)
    assert settings.crsf.crsf_device == "/dev/ttyAMA0"
    assert settings.crsf.crsf_baud == 420000  # CLI overrides the file
    assert settings.logger.sessions_root == "/data"


def test_build_settings_defaults_without_config():
    settings = build_settings(parse_args([]))
    assert isinstance(settings, FpvSettings)
    assert settings.crsf.crsf_baud == 400000


def test_pump_once_ingests_parses_stores_and_evaluates():
    fake = FakeCrsfSerial(echo=False)
    link = CrsfLink(CrsfLinkSettings(), serial=fake)
    link.open()
    clock = ManualClock()
    parser = TelemetryParser()
    store = TelemetryStore()
    monitor = LinkHealthMonitor(HealthSettings(), store, clock)

    fake.feed(link_statistics_bytes(addr=0xEA, uplink_lq=100))
    # A foreign RC frame parses to None (ignored type) and is skipped, not stored.
    from meshsa.fpv.crsf.frame import CrsfFrame, CrsfFrameType

    # Addressed to 0xC8 (not our 0xEA) so rule A does not suppress it; the parser
    # then returns None for the RC type, exercising the skip-None path.
    fake.feed(
        CrsfFrame(addr=0xC8, type=CrsfFrameType.RC_CHANNELS_PACKED, payload=bytes(22)).to_bytes()
    )
    report = pump_once(link, parser, store, monitor, clock)
    # First fresh frame -> NO_DATA pending OK (acquisition hysteresis).
    assert report.state is HealthState.NO_DATA
    # Telemetry was parsed and stored.
    from meshsa.fpv.crsf.telemetry import LinkStatistics

    assert store.latest(LinkStatistics) is not None


def test_pump_once_drops_malformed_known_frame():
    # A CRC-valid LINK_STATISTICS frame with a wrong-length payload parses to a
    # TelemetryParseError. pump_once must drop it (no raise) and keep the loop
    # alive, mirroring crsf_source's per-frame drop-and-continue.
    from meshsa.fpv.crsf.frame import CrsfFrame, CrsfFrameType
    from meshsa.fpv.crsf.telemetry import LinkStatistics

    fake = FakeCrsfSerial(echo=False)
    link = CrsfLink(CrsfLinkSettings(), serial=fake)
    link.open()
    clock = ManualClock()
    parser = TelemetryParser()
    store = TelemetryStore()
    monitor = LinkHealthMonitor(HealthSettings(), store, clock)

    # 10-byte payload is valid; 3 bytes trips LINK_STATISTICS length validation.
    bad = CrsfFrame(addr=0xEA, type=CrsfFrameType.LINK_STATISTICS, payload=bytes(3)).to_bytes()
    fake.feed(bad)
    report = pump_once(link, parser, store, monitor, clock)  # must not raise
    # Nothing was stored: the malformed frame was dropped, not ingested.
    assert store.latest(LinkStatistics) is None
    assert report.state is HealthState.NO_DATA


def test_pump_once_records_to_logger(tmp_path):
    from meshsa.fpv.config import LoggerSettings
    from meshsa.fpv.flight_logger import FlightLogger

    fake = FakeCrsfSerial(echo=False)
    link = CrsfLink(CrsfLinkSettings(), serial=fake)
    link.open()
    clock = ManualClock()
    parser = TelemetryParser()
    store = TelemetryStore()
    monitor = LinkHealthMonitor(HealthSettings(), store, clock)
    logger = FlightLogger(
        LoggerSettings(sessions_root=str(tmp_path)),
        clock=clock,
        git_sha=None,
        now_utc="2026-06-12T00:00:00+00:00",
        session_id="pump",
    )
    logger.start()
    fake.feed(link_statistics_bytes(addr=0xEA))
    pump_once(link, parser, store, monitor, clock, logger=logger)
    logger.close()
    with open(f"{logger.session_dir}/telemetry.jsonl") as fh:
        lines = [json.loads(line) for line in fh if line.strip()]
    assert lines[1]["type"] == "LinkStatistics"
