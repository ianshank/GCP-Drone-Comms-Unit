"""DetectionIngestTransport: UDP datagram -> router inbox (real loopback socket)."""

import asyncio
import socket

import pytest
import structlog

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


# ---- fail-closed bind guard (AUDIT_M2_AUTH surface #10) --------------------
def test_non_loopback_bind_without_token_fails_closed():
    # The guard runs at construction (wiring time), before any socket exists —
    # exercising the real validate_bind logic, not a mock of it.
    with pytest.raises(ValueError, match="refusing to bind the detection ingest transport"):
        DetectionIngestTransport(name="det", host="0.0.0.0", port=0)


def test_non_loopback_bind_without_token_fails_closed_via_registry():
    # The registry factory is the config-driven path operators actually hit.
    with pytest.raises(ValueError, match="refusing to bind"):
        transport_registry.create("detection_ingest", name="det", host="0.0.0.0", port=0)


def test_empty_token_is_no_token():
    with pytest.raises(ValueError, match="without a token"):
        DetectionIngestTransport(name="det", host="0.0.0.0", port=0, token="")


async def test_non_loopback_bind_with_token_warns_unauthenticated_datagrams():
    # Token satisfies the bind guard, but plain UDP cannot check it per-datagram
    # yet — the transport must say so loudly at bind time.
    t = DetectionIngestTransport(name="det", host="0.0.0.0", port=0, token="s3cr3t")
    with structlog.testing.capture_logs() as cap:
        await t.start()
    try:
        assert any(
            entry["log_level"] == "warning" and "not authenticated" in entry["event"]
            for entry in cap
        )
    finally:
        await t.stop()


async def test_loopback_bind_does_not_warn():
    t = DetectionIngestTransport(name="det", host="127.0.0.1", port=0)
    with structlog.testing.capture_logs() as cap:
        await t.start()
    try:
        assert not any(entry["log_level"] == "warning" for entry in cap)
    finally:
        await t.stop()
