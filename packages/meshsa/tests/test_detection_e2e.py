"""End-to-end: a detection UDP datagram becomes a CoT marker on the TAK leg.

Proves the full Phase-A composition through a real node: detection_ingest (UDP source,
`detection` codec -> MARKER Envelope) -> Router re-encodes per target -> `cot` codec
(new MARKER path -> marker_type) -> TAK leg. The unit tests cover each seam; this proves
the router picks the right per-transport codec and the MARKER survives the round.
"""

import asyncio
import json
import socket

import pytest

from meshsa import CotCodec, LoopbackBus, LoopbackTransport, MessageKind, NodeConfig, build_node


def _cfg() -> NodeConfig:
    return NodeConfig.from_mapping(
        {
            "uid": "yolo-gw",
            "callsign": "YGW",
            "tier": "base",
            "transports": [
                {
                    "name": "detections",
                    "type": "detection_ingest",
                    "codec": "detection",
                    "options": {"host": "127.0.0.1", "port": 0},
                },
                {"name": "tak", "type": "loopback", "codec": "cot"},
            ],
        }
    )


async def test_detection_datagram_bridges_to_cot_marker():
    tak_bus = LoopbackBus()
    tak_peer = LoopbackTransport(name="tak-peer", bus=tak_bus)
    node = build_node(_cfg(), transport_kwargs={"tak": {"bus": tak_bus}})

    await node.start()
    try:
        det = next(t for t in node.router.transports if t.name == "detections")
        frame = json.dumps(
            {
                "src": "yolo-cam1",
                "msg_id": "d:1",
                "ts": 1_700_000_000.0,
                "lat": 37.0,
                "lon": -122.0,
                "label": "person",
                "confidence": 0.9,
                "ce": 25.0,
                "track_id": 7,
            }
        ).encode()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.sendto(frame, ("127.0.0.1", det.bound_port))
        sock.close()
        tak_frame = await asyncio.wait_for(tak_peer.stream().__anext__(), timeout=2.0)
    finally:
        await node.stop()

    assert tak_frame.startswith(b"<event")
    assert b'type="a-u-G"' in tak_frame  # rendered as a marker, not a friendly PLI
    cot = CotCodec().decode(tak_frame)
    assert cot.kind is MessageKind.MARKER
    assert cot.payload["detection"]["label"] == "person"
    assert cot.payload["detection"]["track_id"] == 7
    assert cot.payload["position"]["lat"] == pytest.approx(37.0)
