#!/usr/bin/env python3
"""Field example: bridge a real Meshtastic T-Beam to a real FreeTAKServer.

No fakes — this uses the production transports:
  * mesh side : MeshtasticTransport over USB serial, framework JSON envelope
  * tak  side : TakTcpTransport to FreeTAKServer:8087, Cursor-on-Target codec

Inbound CoT from FTS is bridged onto the LoRa mesh as JSON and vice-versa. The TAK
link auto-reconnects with backoff, so the bridge survives the server going away.

Prerequisites:
    pip install meshsa meshtastic pypubsub      # (meshsa from this package)
    # a T-Beam on USB, and a reachable FreeTAKServer

Run:
    python base_node.py --port /dev/ttyUSB0 --fts-host 127.0.0.1 \
        --lat 37.0 --lon -122.0 --callsign BASE1

Every value can also come from the environment (MESHSA_PORT, MESHSA_FTS_HOST, ...);
CLI flags win. Stop with Ctrl-C.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import signal

import structlog

from meshsa import Envelope, NodeConfig, Position, build_node

log = structlog.get_logger("base_node")


def _env(key: str, default: str) -> str:
    return os.environ.get(f"MESHSA_{key}", default)


def _env_int(key: str, default: int) -> int:
    return int(_env(key, str(default)))


def _env_float(key: str, default: float) -> float:
    return float(_env(key, str(default)))


def parse_args() -> argparse.Namespace:
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
    return p.parse_args()


def build_config(args: argparse.Namespace) -> NodeConfig:
    return NodeConfig.from_mapping(
        {
            "uid": args.uid,
            "callsign": args.callsign,
            "tier": "base",
            "pli_interval_s": args.interval,
            "default_stale_s": args.stale,
            "mesh": {"region": args.region},
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
                        "delimiter": args.tcp_delimiter.encode().decode("unicode_escape").encode(),
                        "reconnect": True,
                    },
                    "codec_options": {"stale_s": args.stale},
                },
            ],
        }
    )


async def run(args: argparse.Namespace) -> None:
    node = build_node(build_config(args))

    def on_message(env: Envelope) -> None:
        log.info("rx", kind=env.kind.value, src=env.source_uid, payload=env.payload)

    node.on_message(on_message)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # e.g. Windows
            pass

    await node.start()
    log.info("bridge up", uid=args.uid, mesh_port=args.port, fts=f"{args.fts_host}:{args.fts_port}")
    try:
        while not stop.is_set():
            await node.publish_position(Position(lat=args.lat, lon=args.lon))
            try:
                await asyncio.wait_for(stop.wait(), timeout=node.config.pli_interval_s)
            except asyncio.TimeoutError:
                pass
    finally:
        log.info("shutting down")
        await node.stop()


def main() -> None:
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(20))
    try:
        asyncio.run(run(parse_args()))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
