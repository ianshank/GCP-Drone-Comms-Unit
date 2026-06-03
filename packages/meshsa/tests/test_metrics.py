"""Router observability counters (rx/tx/forwarded/drops/schema_mismatch)."""

import asyncio

from meshsa import (
    Envelope,
    JsonCodec,
    LoopbackBus,
    LoopbackTransport,
    MessageKind,
    Router,
)


def _env(mid, schema=1):
    return Envelope(
        schema_version=schema,
        msg_id=mid,
        ts=1.0,
        source_uid="u",
        kind=MessageKind.CHAT,
        payload={"text": "hi", "to": None},
    )


async def test_publish_increments_tx_per_transport():
    bus = LoopbackBus()
    r = Router(
        [LoopbackTransport(name="a", bus=bus), LoopbackTransport(name="b", bus=bus)], JsonCodec()
    )
    await r.publish(_env("m1"))
    assert r.metrics.tx == 2


async def test_pump_counts_rx_forwarded_and_drops():
    bus_a, bus_b = LoopbackBus(), LoopbackBus()
    src = LoopbackTransport(name="src", bus=bus_a)
    dst = LoopbackTransport(name="dst", bus=bus_b)
    feeder = LoopbackTransport(name="feeder", bus=bus_a)  # injects into src only
    r = Router([src, dst], JsonCodec())
    await r.start()
    await feeder.send(JsonCodec().encode(_env("rx1")))  # valid -> rx + forwarded to dst
    await feeder.send(b"not-json")  # malformed -> dropped_undecodable
    await feeder.send(JsonCodec().encode(_env("bad", schema=99)))  # -> schema_mismatch
    await asyncio.sleep(0.05)
    await r.stop()
    assert r.metrics.rx == 1
    assert r.metrics.forwarded == 1
    assert r.metrics.dropped_undecodable == 1
    assert r.metrics.schema_mismatch == 1
