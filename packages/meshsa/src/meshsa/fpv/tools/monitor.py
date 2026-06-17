"""``fpv-telemetry-monitor`` — live CRSF ingest + link health + echo/CRC counters.

The per-poll glue (:func:`pump_once`) is pure and unit-tested against a scripted
serial; the infinite live loop and the structlog wiring in :func:`main` are
``# pragma: no cover`` (they need real hardware / block forever).
"""

from __future__ import annotations

import argparse

import structlog

from ...cli import configure_logging
from ...protocols import Clock
from ..config import FpvSettings
from ..crsf.link import CrsfLink
from ..crsf.telemetry import TelemetryParser
from ..errors import TelemetryParseError
from ..flight_logger import FlightLogger
from ..link_health import HealthReport, LinkHealthMonitor
from ..protocols import MonotonicClock
from ..telemetry_store import TelemetryStore

_log = structlog.get_logger("meshsa.fpv.monitor")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments (pure; safe to unit-test)."""
    p = argparse.ArgumentParser(prog="fpv-telemetry-monitor")
    p.add_argument("--device", default=None, help="serial device (default from settings)")
    p.add_argument("--baud", type=int, default=None, help="baud rate (default from settings)")
    p.add_argument("--config", default=None, help="FpvSettings JSON file")
    p.add_argument("--record", action="store_true", help="log the session via FlightLogger")
    p.add_argument("--sessions-root", default=None, help="override logger sessions root")
    p.add_argument(
        "--interval", type=float, default=None, help="poll interval seconds (default from settings)"
    )
    p.add_argument("--log-level", default="INFO", help="DEBUG/INFO/WARNING/ERROR")
    return p.parse_args(argv)


def build_settings(args: argparse.Namespace) -> FpvSettings:
    """Build :class:`FpvSettings` from a config file + CLI overrides (no magic numbers)."""
    settings = FpvSettings.from_file(args.config) if args.config else FpvSettings()
    if args.device is not None:
        settings.crsf.crsf_device = args.device
    if args.baud is not None:
        settings.crsf.crsf_baud = args.baud
    if args.sessions_root is not None:
        settings.logger.sessions_root = args.sessions_root
    if args.interval is not None:
        settings.monitor.poll_interval_s = args.interval
    return settings


def pump_once(
    link: CrsfLink,
    parser: TelemetryParser,
    store: TelemetryStore,
    monitor: LinkHealthMonitor,
    clock: Clock,
    *,
    logger: FlightLogger | None = None,
) -> HealthReport:
    """One ingest cycle: poll -> parse -> store (+log) -> evaluate health.

    ``clock`` is any :class:`meshsa.protocols.Clock` (the production
    ``MonotonicClock`` or an injected fake), keeping this helper genuinely pure
    and unit-testable.

    Returns the freshly evaluated :class:`HealthReport`. Echo suppression and CRC
    accounting happen inside ``link.poll_inbound``; this function never sees echoes.

    A CRC-valid but payload-malformed *known* frame raises
    :class:`TelemetryParseError`; it is dropped (logged, then skipped) so a single
    bad frame never tears down the live loop — mirroring
    :meth:`meshsa.transports.crsf_source.CrsfSourceTransport._poll`.
    """
    for frame in link.poll_inbound():
        try:
            msg = parser.parse(frame)
        except TelemetryParseError as exc:
            _log.warning(
                "telemetry parse error; dropping frame", type=frame.type_name, error=str(exc)
            )
            continue
        if msg is None:
            continue
        t = clock.now()
        store.update(msg, t)
        if logger is not None:
            logger.record_telemetry(msg, t)
    return monitor.evaluate()


def run(args: argparse.Namespace) -> None:  # pragma: no cover - live hardware loop
    import time

    settings = build_settings(args)
    clock = MonotonicClock()
    link = CrsfLink(settings.crsf)
    link.open()
    parser = TelemetryParser(settings.parser)
    store = TelemetryStore(settings.logger.store_history_len)
    from ..link_health import ConsoleAlertSink

    monitor = LinkHealthMonitor(settings.health, store, clock, ConsoleAlertSink())
    logger = None
    if args.record:
        logger = FlightLogger(settings.logger, settings_snapshot=settings.model_dump())
        logger.start()
    try:
        while True:
            report = pump_once(link, parser, store, monitor, clock, logger=logger)
            _log.info(
                "health",
                state=report.state.value,
                arm=report.arm_permitted,
                echoes=link.echoes_suppressed,
                crc_errors=link.crc_errors,
            )
            time.sleep(settings.monitor.poll_interval_s)
    except KeyboardInterrupt:
        pass
    finally:
        if logger is not None:
            logger.close()
        link.close()


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - entry point
    args = parse_args(argv)
    configure_logging(args.log_level)
    run(args)
    return 0
