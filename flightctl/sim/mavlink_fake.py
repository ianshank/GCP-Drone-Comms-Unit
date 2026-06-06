#!/usr/bin/env python3
"""Minimal MAVLink simulator — emits HEARTBEAT + GLOBAL_POSITION_INT over UDP.

Lets you exercise the full pipeline (mavlink_source -> telemetry codec -> router ->
cot -> FreeTAKServer/ATAK) with no autopilot and no hardware. Flies a slow circle so
the track visibly moves in ATAK.

    pip install pymavlink            # into your dev/SSD venv
    python flightctl/sim/mavlink_fake.py --endpoint udpout:127.0.0.1:14550 --hz 2

Point a meshsa mavlink_source transport at the matching `udpin:127.0.0.1:14550`
(see flightctl/configs/jetson_gateway.json), or a proxy (mavp2p/mavlink-router).
Nothing is hard-coded: endpoint, rate, centre lat/lon, radius and altitude are flags.
"""

from __future__ import annotations

import argparse
import math
import time


def main() -> None:
    ap = argparse.ArgumentParser(description="Fake MAVLink GLOBAL_POSITION_INT emitter")
    ap.add_argument("--endpoint", default="udpout:127.0.0.1:14550")
    ap.add_argument("--hz", type=float, default=2.0, help="messages per second")
    ap.add_argument("--lat", type=float, default=37.7749, help="circle centre latitude")
    ap.add_argument(
        "--lon", type=float, default=-122.4194, help="circle centre longitude"
    )
    ap.add_argument("--radius-m", type=float, default=200.0)
    ap.add_argument("--alt-m", type=float, default=100.0)
    ap.add_argument("--system-id", type=int, default=1)
    args = ap.parse_args()

    from pymavlink import mavutil

    conn = mavutil.mavlink_connection(args.endpoint, source_system=args.system_id)
    period = 1.0 / args.hz if args.hz > 0 else 0.5
    # ~metres-per-degree at the centre latitude, for a believable circular path.
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = 111_320.0 * max(math.cos(math.radians(args.lat)), 1e-6)
    t0 = time.time()
    print(f"emitting MAVLink on {args.endpoint} at {args.hz} Hz (Ctrl-C to stop)")
    try:
        while True:
            elapsed = time.time() - t0
            ang = (elapsed * 0.1) % (2 * math.pi)  # slow orbit
            lat = args.lat + (args.radius_m * math.sin(ang)) / m_per_deg_lat
            lon = args.lon + (args.radius_m * math.cos(ang)) / m_per_deg_lon
            conn.mav.heartbeat_send(
                mavutil.mavlink.MAV_TYPE_QUADROTOR,
                mavutil.mavlink.MAV_AUTOPILOT_GENERIC,
                0,
                0,
                0,
            )
            conn.mav.global_position_int_send(
                int(elapsed * 1000) & 0xFFFFFFFF,  # time_boot_ms
                int(lat * 1e7),
                int(lon * 1e7),  # lat, lon (degE7)
                int(args.alt_m * 1000),
                int(args.alt_m * 1000),  # alt, relative_alt (mm)
                0,
                0,
                0,  # vx, vy, vz
                int(math.degrees(ang) * 100) % 36000,  # hdg (cdeg)
            )
            time.sleep(period)
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
