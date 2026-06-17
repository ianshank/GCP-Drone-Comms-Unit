#!/usr/bin/env python3
"""rc_bridge.py — pilot a Betaflight FC from the Jetson over USB (MSP RC) + telemetry.

Reads the RadioMaster/EdgeTX radio at ``/dev/input/js0`` (USB joystick mode), maps the
sticks/switches to RC channels, and streams ``MSP_SET_RAW_RC`` to the FC at a fixed rate
(Betaflight **Receiver = MSP**). The *same* board handle is decimated to also poll telemetry
(GPS/battery/RSSI/attitude) and forward it to FreeTAKServer as a CoT track — one process owns
the one exclusive serial handle, so this CANNOT run alongside ``FC_MODE=msp`` (both want the FC).

This is the ops/daemon layer (cf. ``run_gateway.py``); the tested control logic lives in
``meshsa.rc``. The serial-owning RC loop is a sync thread; CoT goes out on an asyncio loop,
bridged with ``run_coroutine_threadsafe``.

⚠️ SAFETY — drives real motors. Bench-test **with props off**. Starts disarmed/throttle-min,
never auto-arms, fails safe on stale input, and disarms on shutdown. Use ``--dry-run`` first
to calibrate the channel mapping with no writes to the FC.

Examples:
  rc_bridge.py --dry-run                         # print mapped channels, never touch the FC
  rc_bridge.py --monitor                         # send RC + log MSP_RC read-back (no TAK)
  rc_bridge.py --tak-host 127.0.0.1              # full: pilot + telemetry track to FTS
"""

from __future__ import annotations

import argparse
import asyncio
import signal
from typing import Any

import structlog

from meshsa import (
    JoystickChannelSource,
    MspPilot,
    RcMapping,
    RoundRobinTelemetry,
    default_mapping,
    load_mapping,
    make_cot_publisher,
)
from meshsa.rc import FileJoystickReader, MspRcSink
from meshsa.transports import TakTcpTransport
from meshsa.transports.msp_source import _msp_read

_log = structlog.get_logger("flightctl.rc_bridge")


def _log_future_error(fut: Any) -> None:  # pragma: no cover - loop-thread callback
    exc = fut.exception()
    if exc is not None:
        _log.warning("cot send failed", exc_info=exc)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Joystick → MSP RC pilot bridge for Betaflight.")
    p.add_argument("--device", default="/dev/flightctl-fc", help="FC serial (udev symlink or /dev/ttyACM0)")
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--js", default="/dev/input/js0", help="joystick device")
    p.add_argument("--hz", type=float, default=50.0, help="RC send rate")
    p.add_argument("--serial-timeout", type=float, default=0.1, help="yamspy serial read timeout (s)")
    p.add_argument("--mapping", help="path to an RcMapping JSON (defaults to the EdgeTX-Pocket map)")
    p.add_argument("--dry-run", action="store_true", help="print channels; never write to the FC")
    p.add_argument("--monitor", action="store_true", help="also read MSP_RC back and log it")
    # telemetry → TAK (omit --tak-host to disable telemetry)
    p.add_argument("--tak-host", help="FreeTAKServer host for CoT (omit to disable telemetry)")
    p.add_argument("--tak-port", type=int, default=8087)
    p.add_argument(
        "--telemetry-interval",
        type=float,
        default=0.3,
        help="seconds between MSP telemetry reads (one message per read, round-robin)",
    )
    p.add_argument("--source-uid", default="fc-1")
    p.add_argument("--callsign", default="FC1")
    p.add_argument("--pli-type", default="a-f-A-M-F-Q")
    p.add_argument("--fallback-lat", type=float)
    p.add_argument("--fallback-lon", type=float)
    p.add_argument("--fallback-hae", type=float, default=0.0)
    return p.parse_args(argv)


def _mapping_for(path: str | None) -> RcMapping:
    return default_mapping() if path is None else load_mapping(path)


def _make_board(device: str, baud: int, timeout: float) -> Any:  # pragma: no cover - needs FC
    from yamspy import MSPy

    board = MSPy(device=device, loglevel="WARNING", baudrate=baud)
    if board.connect(trials=board.ser_trials) != 0:
        raise ConnectionError(
            f"could not connect to FC at {device} (check device, 'dialout' group, and that "
            "Betaflight Configurator is disconnected)"
        )
    board.conn.timeout = timeout  # bound per-read blocking so a quiet FC can't stall RC
    return board


class _PrintSink:  # pragma: no cover - interactive dry-run aid
    def send(self, channels: Any) -> None:
        print("RC", [int(c) for c in channels], flush=True)


async def _amain(args: argparse.Namespace) -> int:  # pragma: no cover - ops entrypoint
    mapping = _mapping_for(args.mapping)
    reader = FileJoystickReader(args.js)
    source = JoystickChannelSource(reader, mapping)

    # --- dry run: no FC, no TAK, just prove the stick → channel mapping ---
    if args.dry_run:
        pilot = MspPilot(source, _PrintSink(), hz=args.hz)
        return await _run_until_signal(pilot, taks=[])

    board = _make_board(args.device, args.baud, args.serial_timeout)
    sink = MspRcSink(board)
    loop = asyncio.get_running_loop()

    taks: list[Any] = []
    on_telemetry = None
    if args.tak_host:
        tak = TakTcpTransport(name="tak", host=args.tak_host, port=args.tak_port)
        await tak.start()
        taks.append(tak)
        # Round-robin telemetry (one MSP read per call) so the poll never stalls the RC loop.
        frame_source = RoundRobinTelemetry(
            board,
            source_uid=args.source_uid,
            callsign=args.callsign,
            fallback_lat=args.fallback_lat,
            fallback_lon=args.fallback_lon,
            fallback_hae=args.fallback_hae,
        )

        def send_cot(cot: bytes) -> None:
            fut = asyncio.run_coroutine_threadsafe(tak.send(cot), loop)
            fut.add_done_callback(_log_future_error)  # don't drop send errors silently

        publish = make_cot_publisher(frame_source, send_cot, pli_type=args.pli_type)
        if args.monitor:

            def on_telemetry() -> None:
                publish()
                _log_rc_readback(board, mapping)
        else:
            on_telemetry = publish

    elif args.monitor:

        def on_telemetry() -> None:
            _log_rc_readback(board, mapping)

    pilot = MspPilot(
        source,
        sink,
        hz=args.hz,
        telemetry_interval_s=args.telemetry_interval,
        on_telemetry=on_telemetry,
        disarm=source.disarm_channels(),
    )
    _log.info("rc bridge up", device=args.device, js=args.js, hz=args.hz, tak=bool(args.tak_host))
    return await _run_until_signal(pilot, taks=taks, board=board)


def _log_rc_readback(board: Any, mapping: RcMapping) -> None:  # pragma: no cover - needs FC
    try:
        _msp_read(board, "MSP_RC")
        n = len(mapping.channels)
        _log.info("MSP_RC readback", channels=board.RC["channels"][:n])
    except Exception:
        _log.warning("MSP_RC readback failed")


async def _run_until_signal(
    pilot: MspPilot, *, taks: list[Any], board: Any | None = None
) -> int:  # pragma: no cover
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    pilot.start()
    try:
        await stop.wait()
    finally:
        pilot.stop()  # emits the final disarm frame FIRST, while the serial is still open
        close = getattr(board, "close", None)
        if callable(close):
            try:
                close()  # release the FC serial so a restart can re-open it
            except Exception:
                _log.debug("board close error")
        for t in taks:
            await t.stop()
    return 0


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - ops entrypoint
    return asyncio.run(_amain(_parse_args(argv)))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
