"""DetectionIngestTransport: UDP datagram -> router inbox (real loopback socket)."""

import asyncio
import socket

from meshsa import transport_registry
from meshsa.transports import DetectionIngestTransport


def test_registered_in_transport_registry():
    assert transport_registry.has("detection_ingest")
    t = transport_registry.create("detection_ingest", name="det", port=0)
    assert isinstance(t, DetectionIngestTransport)


async def test_datagram_is_ingested_and_streamed():
    t = DetectionIngestTransport(name="det", host="127.0.0.1", port=0)
    await t.start()
    try:
        assert t.bound_port and t.bound_port > 0
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.sendto(b'{"label":"person"}', ("127.0.0.1", t.bound_port))
        sock.close()
        frame = await asyncio.wait_for(t.stream().__anext__(), timeout=1.0)
        assert frame == b'{"label":"person"}'
    finally:
        await t.stop()


async def test_send_is_noop_and_stop_is_safe():
    t = DetectionIngestTransport(name="det", host="127.0.0.1", port=0)
    await t.start()
    assert await t.send(b"ignored") is None  # receive-only
    await t.stop()
    await t.stop()  # idempotent (endpoint already None)
