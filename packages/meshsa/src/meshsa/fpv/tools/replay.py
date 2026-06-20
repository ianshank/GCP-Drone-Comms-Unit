"""``fpv-log-replay`` — replay ``telemetry.jsonl`` through store + monitor.

Threshold tuning is an offline, data-driven activity: replay a recorded session
under *candidate* :class:`HealthSettings` and compare the resulting health
outcomes. The replay core is pure and unit-tested; ``main`` is the entry point.
"""

from __future__ import annotations

import argparse
from typing import Any

import structlog

from ...cli import configure_logging
from ..config import HealthSettings
from ..crsf.telemetry import message_from_record
from ..dataset import read_jsonl
from ..errors import TelemetryParseError
from ..link_health import HealthReport, LinkHealthMonitor, worst_state
from ..telemetry_store import TelemetryStore

_log = structlog.get_logger("meshsa.fpv.replay")


class _ReplayClock:
    """A clock pinned to each record's monotonic timestamp during replay."""

    def __init__(self) -> None:
        self.t = 0.0

    def now(self) -> float:
        return self.t


def replay_records(
    records: list[dict[str, Any]],
    *,
    health_settings: HealthSettings | None = None,
    store_history_len: int = 512,
) -> list[HealthReport]:
    """Replay telemetry ``records`` and return the per-record health reports."""
    store = TelemetryStore(store_history_len)
    clock = _ReplayClock()
    monitor = LinkHealthMonitor(health_settings or HealthSettings(), store, clock)
    reports: list[HealthReport] = []
    for rec in records:
        # Guard the raw key access: a corrupt log line or a forward dataset that
        # reshaped the record must fail with TelemetryParseError (uniform with
        # message_from_record), not a bare KeyError that crashes replay.
        try:
            rec_type, data, t = rec["type"], rec["data"], rec["t"]
        except KeyError as exc:
            raise TelemetryParseError(f"malformed replay record: missing key {exc}") from exc
        msg = message_from_record(rec_type, data)
        clock.t = t
        store.update(msg, t)
        reports.append(monitor.evaluate())
    return reports


def replay_file(path: str, *, health_settings: HealthSettings | None = None) -> list[HealthReport]:
    """Read a ``telemetry.jsonl`` file and replay it (schema-compat enforced)."""
    _header, records = read_jsonl(path)
    return replay_records(records, health_settings=health_settings)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="fpv-log-replay")
    p.add_argument("telemetry_jsonl", help="path to a session telemetry.jsonl")
    p.add_argument("--config", default=None, help="candidate FpvSettings JSON (health block)")
    p.add_argument("--log-level", default="INFO", help="DEBUG/INFO/WARNING/ERROR")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - entry point
    from ..config import FpvSettings

    args = parse_args(argv)
    configure_logging(args.log_level)
    health = FpvSettings.from_file(args.config).health if args.config else HealthSettings()
    reports = replay_file(args.telemetry_jsonl, health_settings=health)
    worst = worst_state(r.state for r in reports)
    _log.info("replay complete", records=len(reports), worst_state=worst.value)
    return 0
