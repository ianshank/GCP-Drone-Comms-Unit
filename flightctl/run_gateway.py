#!/usr/bin/env python3
"""Run a meshsa flight-control gateway node from a JSON config until interrupted.

A thin, dependency-free runner around ``meshsa.build_node`` for systemd. The node's
transports/codecs (e.g. ``mavlink_source``+``telemetry`` bridged to ``tak_tcp``+``cot``)
are entirely defined by the config file — see flightctl/configs/jetson_gateway.json.

    python flightctl/run_gateway.py --config flightctl/configs/jetson_gateway.json
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import signal

from meshsa import NodeConfig, build_node
from meshsa.cli import configure_logging


async def _run(config_path: str) -> None:
    node = build_node(NodeConfig.from_file(config_path))
    await node.start()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        # add_signal_handler is unimplemented on some platforms (e.g. Windows);
        # match meshsa.cli.run and degrade gracefully instead of crashing.
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)
    try:
        await stop.wait()
    finally:
        await node.stop()


def main() -> None:
    ap = argparse.ArgumentParser(description="Run a meshsa gateway node from a config file")
    ap.add_argument("--config", required=True, help="path to a NodeConfig JSON file")
    args = ap.parse_args()
    configure_logging(os.environ.get("MESHSA_LOG_LEVEL", "INFO"))
    asyncio.run(_run(args.config))


if __name__ == "__main__":
    main()
