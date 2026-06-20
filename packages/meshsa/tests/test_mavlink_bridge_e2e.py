"""End-to-end (no network): a MAVLink fix becomes a CoT *air* track on the TAK leg.

This is the architectural proof for the flight-control integration — a telemetry
source transport, decoded by the ``telemetry`` codec, bridged by the router and
re-encoded by a ``cot`` codec instance configured (via ``codec_options``) with an
air ``pli_type`` — all through ``build_node`` with zero core changes, mirroring
``test_bridge_e2e.py``.
"""

import asyncio
import xml.etree.ElementTree as ET

import pytest
from conftest import FakeClock
from test_mavlink_source import FakeConn, FakeMsg

from meshsa import LoopbackBus, LoopbackTransport, NodeConfig, build_node


def _gateway_config() -> NodeConfig:
    return NodeConfig.from_mapping(
        {
            "uid": "gw-1",
            "callsign": "GW1",
            "tier": "base",
            "transports": [
                {
                    "name": "drone",
                    "type": "mavlink_source",
                    "codec": "telemetry",
                    "options": {"source_uid": "uav-1", "callsign": "UAV1"},
                },
                {
                    "name": "tak",
                    "type": "loopback",
                    "codec": "cot",
                    "codec_options": {"pli_type": "a-f-A-M-F-Q", "stale_s": 10},
                },
            ],
        }
    )


async def test_mavlink_fix_bridges_to_cot_air_track():
    conn = FakeConn()
    tak_bus = LoopbackBus()
    tak_peer = LoopbackTransport(name="tak-peer", bus=tak_bus)
    node = build_node(
        _gateway_config(),
        transport_kwargs={
            "drone": {"connection": conn, "clock": FakeClock()},
            "tak": {"bus": tak_bus},
        },
    )

    await node.start()
    try:
        conn.feed(FakeMsg(377749000, -1224194000, 100000))
        tak_frame = await asyncio.wait_for(tak_peer.stream().__anext__(), timeout=2.0)
    finally:
        await node.stop()

    ev = ET.fromstring(tak_frame)
    assert ev.tag == "event"
    assert ev.attrib["type"].startswith("a-f-A")  # air track, not the default ground type
    pt = ev.find("point")
    assert pt is not None
    assert float(pt.attrib["lat"]) == pytest.approx(37.7749)
    assert float(pt.attrib["lon"]) == pytest.approx(-122.4194)
    assert node.router.metrics.rx >= 1
    assert node.router.metrics.forwarded >= 1
