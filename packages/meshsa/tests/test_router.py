import asyncio

from meshsa import (
    Envelope,
    JsonCodec,
    LoopbackBus,
    LoopbackTransport,
    MessageKind,
    Router,
    RouterConfig,
)


def _env(mid: str) -> Envelope:
    return Envelope(msg_id=mid, ts=1.0, source_uid="u", kind=MessageKind.PLI)


async def test_publish_sends_on_all_transports():
    bus = LoopbackBus()
    t = LoopbackTransport(name="t", bus=bus)
    r = Router([t], JsonCodec())
    await r.publish(_env("m1"))
    assert len(t.sent) == 1


async def test_inbound_delivered_to_subscriber_once():
    bus = LoopbackBus()
    rx = LoopbackTransport(name="rx", bus=bus)
    tx = LoopbackTransport(name="tx", bus=bus)  # peer that injects traffic
    received = []
    r = Router([rx], JsonCodec())
    r.subscribe(lambda e: received.append(e.msg_id))
    await r.start()
    await tx.send(JsonCodec().encode(_env("m9")))
    await tx.send(JsonCodec().encode(_env("m9")))  # duplicate id -> deduped
    await asyncio.sleep(0.05)
    await r.stop()
    assert received == ["m9"]


async def test_bridge_forwards_between_transports():
    bus1, bus2 = LoopbackBus(), LoopbackBus()
    t1 = LoopbackTransport(name="t1", bus=bus1)
    t2 = LoopbackTransport(name="t2", bus=bus2)
    injector = LoopbackTransport(name="inj", bus=bus1)  # on bus1 with t1
    listener = LoopbackTransport(name="lst", bus=bus2)  # on bus2 with t2
    r = Router([t1, t2], JsonCodec())
    await r.start()
    await injector.send(JsonCodec().encode(_env("bridgeme")))
    got = await asyncio.wait_for(listener.stream().__anext__(), timeout=1.0)
    await r.stop()
    assert JsonCodec().decode(got).msg_id == "bridgeme"


async def test_dedupe_cache_evicts_oldest():
    r = Router([], JsonCodec(), config=RouterConfig(dedupe_cache_size=2))
    assert r._mark_seen("a") is True
    assert r._mark_seen("b") is True
    assert r._mark_seen("a") is False
    r._mark_seen("c")  # evicts "a"
    assert r._mark_seen("a") is True  # seen again after eviction


async def test_async_subscriber_supported():
    bus = LoopbackBus()
    rx = LoopbackTransport(name="rx", bus=bus)
    tx = LoopbackTransport(name="tx", bus=bus)
    seen = []

    async def handler(e):
        seen.append(e.msg_id)

    r = Router([rx], JsonCodec())
    r.subscribe(handler)
    await r.start()
    await tx.send(JsonCodec().encode(_env("async1")))
    await asyncio.sleep(0.05)
    await r.stop()
    assert seen == ["async1"]


async def test_router_drops_undecodable_frame():
    bus = LoopbackBus()
    rx = LoopbackTransport(name="rx", bus=bus)
    tx = LoopbackTransport(name="tx", bus=bus)
    seen = []
    r = Router([rx], JsonCodec())
    r.subscribe(lambda e: seen.append(e))
    await r.start()
    await tx.send(b"garbage")
    await asyncio.sleep(0.05)
    await r.stop()
    assert seen == []


async def test_dedupe_cache_bounded_at_scale():
    # Eviction must hold the cache at dedupe_cache_size even under heavy churn.
    r = Router([], JsonCodec(), config=RouterConfig(dedupe_cache_size=10))
    for i in range(100):
        assert r._mark_seen(f"id-{i}") is True
    assert len(r._seen) == 10  # bounded
    assert r._mark_seen("id-99") is False  # most-recent still known
    assert r._mark_seen("id-0") is True  # oldest long since evicted -> new again
