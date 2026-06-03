#!/usr/bin/env python3
"""Field example: bridge a real Meshtastic T-Beam to a real FreeTAKServer.

The implementation now lives in the importable :mod:`meshsa.cli` (so the example
folder stays demonstrative-only); this module re-exports it for backward
compatibility and as a runnable script.

No fakes — this uses the production transports:
  * mesh side : MeshtasticTransport over USB serial, framework JSON envelope
  * tak  side : TakTcpTransport to FreeTAKServer:8087, Cursor-on-Target codec

Run:
    python -m meshsa.examples.base_node --port /dev/ttyUSB0 --fts-host 127.0.0.1 \
        --lat 37.0 --lon -122.0 --callsign BASE1
    # or the installed console script:
    meshsa-base --port /dev/ttyUSB0 --fts-host 127.0.0.1 --callsign BASE1

Every value can also come from the environment (MESHSA_PORT, MESHSA_FTS_HOST, ...);
CLI flags win. Stop with Ctrl-C.
"""

from __future__ import annotations

from meshsa.cli import build_config, main, parse_args, run

__all__ = ["build_config", "main", "parse_args", "run"]


if __name__ == "__main__":
    main()
