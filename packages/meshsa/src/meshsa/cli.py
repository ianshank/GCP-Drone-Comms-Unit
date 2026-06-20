#!/usr/bin/env python3
"""``meshsa-base`` console entry point: a real Meshtastic <-> FreeTAKServer bridge.

The pure, testable pieces (`parse_args`, `build_config`) live here and are unit
tested; the live orchestration (`run`/`main` — signals, ``asyncio.run``, the node
lifecycle, the publish loop and the optional /healthz server) is integration glue
marked ``# pragma: no cover``. See ``meshsa.examples.base_node`` for a runnable
demonstration that re-exports these.

Every flag also reads from the environment (``MESHSA_PORT``, ``MESHSA_FTS_HOST``,
...); CLI flags win. Stop with Ctrl-C.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import os
import signal

import structlog

from ._parsing import parse_float, parse_int
from .config import NodeConfig
from .health import serve_healthz
from .models import Envelope, Position
from .node import build_node

log = structlog.get_logger("meshsa.cli")


def _env(key: str, default: str) -> str:
    return os.environ.get(f"MESHSA_{key}", default)


def _env_int(key: str, default: int) -> int:
    return parse_int(f"MESHSA_{key}", _env(key, str(default)))


def _env_float(key: str, default: float) -> float:
    return parse_float(f"MESHSA_{key}", _env(key, str(default)))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Meshtastic <-> FreeTAKServer bridge node")
    p.add_argument("--port", default=_env("PORT", "/dev/ttyUSB0"), help="T-Beam serial device")
    p.add_argument(
        "--portnum",
        type=int,
        default=_env_int("PORTNUM", 256),
        help="Meshtastic app portnum (default 256 / PRIVATE_APP)",
    )
    p.add_argument("--region", default=_env("MESH_REGION", "US"))
    p.add_argument("--fts-host", default=_env("FTS_HOST", "127.0.0.1"))
    p.add_argument("--fts-port", type=int, default=_env_int("FTS_PORT", 8087))
    p.add_argument("--uid", default=_env("UID", "base-1"))
    p.add_argument("--callsign", default=_env("CALLSIGN", "BASE1"))
    p.add_argument("--lat", type=float, default=_env_float("LAT", 0.0))
    p.add_argument("--lon", type=float, default=_env_float("LON", 0.0))
    p.add_argument(
        "--interval",
        type=float,
        default=_env_float("PLI_INTERVAL_S", 30.0),
        help="seconds between own-position broadcasts",
    )
    p.add_argument(
        "--stale",
        type=float,
        default=_env_float("COT_STALE_S", 120.0),
        help="CoT stale window in seconds",
    )
    p.add_argument(
        "--tcp-delimiter",
        default=_env("TCP_DELIMITER", ""),
        help="bytes appended to each CoT frame on TCP (e.g. '\\n')",
    )
    p.add_argument("--health", action="store_true", default=_env("HEALTH", "") != "")
    p.add_argument("--healthz-host", default=_env("HEALTHZ_HOST", "127.0.0.1"))
    p.add_argument("--healthz-port", type=int, default=_env_int("HEALTHZ_PORT", 8088))
    p.add_argument(
        "--log-level",
        default=_env("LOG_LEVEL", "INFO"),
        help="log verbosity: DEBUG/INFO/WARNING/ERROR (env MESHSA_LOG_LEVEL)",
    )
    return p.parse_args(argv)


def log_level_num(name: str) -> int:
    """Map a level name (case-insensitive) to its numeric value; unknown -> INFO."""
    value = logging.getLevelName(name.upper())
    return value if isinstance(value, int) else logging.INFO


def configure_logging(level: str) -> None:
    """Configure structlog's filtering level from a level name.

    Shared by every console entry point (``meshsa-base``, the ``fpv-*`` tools and the
    flightctl gateway runner) so the structlog wiring lives in exactly one place.
    """
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(log_level_num(level)))


def _delimiter_bytes(raw: str) -> bytes:
    """Interpret a delimiter string with backslash escapes (e.g. '\\n') as bytes."""
    return raw.encode().decode("unicode_escape").encode()


def build_config(args: argparse.Namespace) -> NodeConfig:
    return NodeConfig.from_mapping(
        {
            "uid": args.uid,
            "callsign": args.callsign,
            "tier": "base",
            "pli_interval_s": args.interval,
            "default_stale_s": args.stale,
            "mesh": {"region": args.region},
            "health": {
                "enabled": args.health,
                "host": args.healthz_host,
                "port": args.healthz_port,
            },
            "transports": [
                {
                    "name": "mesh",
                    "type": "meshtastic",
                    "codec": "compact",  # LoRa-sized binary; JSON won't fit a packet
                    "options": {
                        "connection": "serial",
                        "port": args.port,
                        "portnum": args.portnum,
                    },
                },
                {
                    "name": "tak",
                    "type": "tak_tcp",
                    "codec": "cot",
                    "options": {
                        "host": args.fts_host,
                        "port": args.fts_port,
                        "delimiter": _delimiter_bytes(args.tcp_delimiter),
                        "reconnect": True,
                    },
                    "codec_options": {"stale_s": args.stale},
                },
            ],
        }
    )


async def run(args: argparse.Namespace) -> None:  # pragma: no cover - live orchestration
    node = build_node(build_config(args))

    def on_message(env: Envelope) -> None:
        log.info("rx", kind=env.kind.value, src=env.source_uid, payload=env.payload)

    node.on_message(on_message)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):  # e.g. Windows
            loop.add_signal_handler(sig, stop.set)

    await node.start()
    health_runner = None
    if node.config.health.enabled:
        health_runner = await serve_healthz(node, node.config.health.host, node.config.health.port)
        log.info("healthz up", host=node.config.health.host, port=node.config.health.port)
    log.info("bridge up", uid=args.uid, mesh_port=args.port, fts=f"{args.fts_host}:{args.fts_port}")
    try:
        while not stop.is_set():
            await node.publish_position(Position(lat=args.lat, lon=args.lon))
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=node.config.pli_interval_s)
    finally:
        log.info("shutting down")
        await node.stop()
        if health_runner is not None:
            await health_runner.cleanup()


def main() -> None:  # pragma: no cover - process entry point
    args = parse_args()
    configure_logging(args.log_level)
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(run(args))


if __name__ == "__main__":  # pragma: no cover
    main()
