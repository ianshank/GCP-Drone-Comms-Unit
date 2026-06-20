"""fpv-log-replay: deterministic replay + roundtrip through a logged session."""

from __future__ import annotations

import os

import pytest
from _fpv_helpers import ManualClock

from meshsa.fpv.config import HealthSettings, LoggerSettings
from meshsa.fpv.crsf.telemetry import GpsSensor, LinkStatistics, message_from_record
from meshsa.fpv.errors import TelemetryParseError
from meshsa.fpv.flight_logger import FlightLogger
from meshsa.fpv.link_health import HealthState
from meshsa.fpv.tools.replay import parse_args, replay_file, replay_records


def _ls_record(t: float, lq: int) -> dict:
    msg = LinkStatistics(-60, -60, lq, 8, 0, 0, 100, -60, 100, 8)
    from dataclasses import asdict

    return {"t": t, "type": "LinkStatistics", "data": asdict(msg)}


def test_message_from_record_roundtrip_and_unknown():
    rec = _ls_record(1.0, 90)
    msg = message_from_record(rec["type"], rec["data"])
    assert isinstance(msg, LinkStatistics)
    assert msg.uplink_lq == 90
    with pytest.raises(TelemetryParseError, match="unknown telemetry record type"):
        message_from_record("Nonexistent", {})


def test_message_from_record_malformed_data_raises_parse_error():
    # A known type whose payload is missing/extra fields (log corruption or a
    # forward dataset that reshaped the record) must fail with TelemetryParseError
    # rather than a bare TypeError that crashes replay.
    with pytest.raises(TelemetryParseError, match="malformed data for LinkStatistics"):
        message_from_record("LinkStatistics", {"uplink_lq": 90})  # missing fields
    with pytest.raises(TelemetryParseError, match="malformed data for GpsSensor"):
        message_from_record("GpsSensor", {"unexpected_field": 1})  # extra/wrong field


def test_replay_records_malformed_record_raises_parse_error():
    # A record missing a required key (corrupt log line / forward dataset that
    # reshaped the record) raises TelemetryParseError, not a bare KeyError that
    # crashes the replay loop.
    with pytest.raises(TelemetryParseError, match="missing key"):
        replay_records([{"type": "LinkStatistics"}])  # missing "data" and "t"


def test_message_from_record_roundtrip_gps():
    # GpsSensor is a v2 dataset record type; it must round-trip through replay.
    from dataclasses import asdict

    original = GpsSensor(
        lat_deg=37.7749,
        lon_deg=-122.4194,
        ground_speed_kmh=12.3,
        heading_deg=180.0,
        altitude_m=120,
        satellites=9,
    )
    rebuilt = message_from_record("GpsSensor", asdict(original))
    assert rebuilt == original


def test_replay_records_reproduces_health_sequence():
    # t spans the hysteresis window so acquisition reaches OK, then degrades.
    records = [_ls_record(0.0, 100), _ls_record(3.0, 100), _ls_record(4.0, 10)]
    reports = replay_records(records)
    assert [r.state for r in reports] == [
        HealthState.NO_DATA,
        HealthState.OK,
        HealthState.CRITICAL,
    ]


def test_replay_under_candidate_thresholds_changes_outcome():
    records = [_ls_record(0.0, 100), _ls_record(3.0, 100), _ls_record(4.0, 65)]
    # Default warn floor 70 -> lq 65 is WARN.
    default = replay_records(records)
    assert default[-1].state is HealthState.WARN
    # A laxer candidate threshold (warn 60) keeps it OK.
    lax = replay_records(records, health_settings=HealthSettings(health_lq_warn=60))
    assert lax[-1].state is HealthState.OK


def test_replay_file_roundtrip_from_logged_session(tmp_path):
    logger = FlightLogger(
        LoggerSettings(sessions_root=str(tmp_path)),
        clock=ManualClock(),
        git_sha=None,
        now_utc="2026-06-12T00:00:00+00:00",
        session_id="replay",
    )
    logger.start()
    logger.record_telemetry(LinkStatistics(-60, -60, 100, 8, 0, 0, 100, -60, 100, 8), t=0.0)
    logger.record_telemetry(LinkStatistics(-60, -60, 100, 8, 0, 0, 100, -60, 100, 8), t=3.0)
    logger.close()
    reports = replay_file(os.path.join(logger.session_dir, "telemetry.jsonl"))
    assert [r.state for r in reports] == [HealthState.NO_DATA, HealthState.OK]


def test_parse_args_requires_path():
    args = parse_args(["sessions/x/telemetry.jsonl"])
    assert args.telemetry_jsonl.endswith("telemetry.jsonl")
