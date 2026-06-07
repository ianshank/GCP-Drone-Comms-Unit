"""End-to-end (no hardware, no network): a Betaflight MSP sample becomes a CoT *air* track.

Mirrors ``test_mavlink_bridge_e2e.py`` but for the ``msp_source`` path, and proves the two
features that only had piecewise unit coverage actually survive the full router + codec chain:
the GPS-less **fallback** position, and the battery/RSSI/attitude **remarks** reaching the CoT
``<detail><remarks>`` element. The board + poll are injected, so no FC/serial is needed.
"""

import asyncio
import xml.etree.ElementTree as ET

import pytest
from conftest import FakeClock
from test_msp_source import FakeBoard, _fix_poll

from meshsa import LoopbackBus, LoopbackTransport, NodeConfig, build_node


def _gateway_config() -> NodeConfig:
    return NodeConfig.from_mapping(
        {
            "uid": "gw-1",
            "callsign": "GW1",
            "tier": "base",
            "transports": [
                {
                    "name": "fc",
                    "type": "msp_source",
                    "codec": "telemetry",
                    "options": {
                        "source_uid": "uav-1",
                        "callsign": "UAV1",
                        "fallback_lat": 37.0,
                        "fallback_lon": -122.0,
                        "poll_interval_s": 0.01,
                    },
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


async def _run_once(poll) -> bytes:
    tak_bus = LoopbackBus()
    tak_peer = LoopbackTransport(name="tak-peer", bus=tak_bus)
    node = build_node(
        _gateway_config(),
        transport_kwargs={
            "fc": {"board": FakeBoard(), "poll": poll, "clock": FakeClock()},
            "tak": {"bus": tak_bus},
        },
    )
    await node.start()
    try:
        return await asyncio.wait_for(tak_peer.stream().__anext__(), timeout=2.0)
    finally:
        await node.stop()


async def test_msp_gps_fix_bridges_to_cot_air_track():
    frame = await _run_once(_fix_poll({"lat": 377749000, "lon": -1224194000, "alt": 100}))
    ev = ET.fromstring(frame)
    assert ev.attrib["type"].startswith("a-f-A")  # air track, not the ground default
    pt = ev.find("point")
    assert float(pt.attrib["lat"]) == pytest.approx(37.7749)
    assert float(pt.attrib["lon"]) == pytest.approx(-122.4194)


async def test_msp_no_fix_uses_fallback_track():
    # GPS-less bench FC: poll never returns a fix → the configured fallback keeps it on the map.
    frame = await _run_once(_fix_poll())  # no fix, ever
    pt = ET.fromstring(frame).find("point")
    assert float(pt.attrib["lat"]) == pytest.approx(37.0)  # fallback degrees, not coord-scaled
    assert float(pt.attrib["lon"]) == pytest.approx(-122.0)


async def test_msp_telemetry_remarks_reach_cot_xml():
    # Battery/RSSI/attitude must survive transport → telemetry codec → router → cot codec.
    frame = await _run_once(_fix_poll({"vbat": 11.84, "rssi": 1023, "roll": 2.0}))
    ev = ET.fromstring(frame)
    remarks = ev.find("detail/remarks")
    assert remarks is not None and remarks.text is not None
    assert "VBAT 11.8V" in remarks.text and "RSSI 1023" in remarks.text and "ROLL 2" in remarks.text
