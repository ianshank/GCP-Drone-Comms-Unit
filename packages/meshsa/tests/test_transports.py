import structlog

from meshsa import LoopbackBus, LoopbackTransport, NullTransport
from meshsa.transports.base import _DROP_LOG_INTERVAL


async def test_loopback_bus_delivers_to_others_not_self():
    bus = LoopbackBus()
    a = LoopbackTransport(name="a", bus=bus)
    b = LoopbackTransport(name="b", bus=bus)
    await a.start()
    await b.start()
    await a.send(b"hello")
    # b hears it
    it = b.stream()
    got = await it.__anext__()
    assert got == b"hello"
    assert a._inbox.empty()  # no self-echo
    await a.stop()
    await b.stop()


async def test_null_transport_drops():
    n = NullTransport(name="n")
    await n.send(b"x")
    assert n._inbox.empty()


async def test_inbox_full_drops_newest_and_counts():
    # Configurable queue_maxsize is now live; a full inbox drops + counts
    # rather than blocking the reader.
    t = NullTransport(name="n", queue_maxsize=1)
    await t._ingest(b"a")  # fills the single slot
    await t._ingest(b"b")  # full -> newest dropped, counted
    assert t.dropped_inbox_full == 1
    assert t._inbox.qsize() == 1
    assert await t._inbox.get() == b"a"  # oldest retained (drop-newest semantics)


async def test_inbox_full_warning_logs_first_drop_then_throttles():
    # A stuck consumer can drop thousands of frames a second; only the first drop
    # and every Nth one after should log, not every single one.
    t = NullTransport(name="n", queue_maxsize=1)
    await t._ingest(b"seed")  # fills the slot without dropping
    with structlog.testing.capture_logs() as cap:
        for _ in range(_DROP_LOG_INTERVAL + 50):
            await t._ingest(b"x")
    warnings = [e for e in cap if e["log_level"] == "warning"]
    assert [w["dropped_inbox_full"] for w in warnings] == [1, _DROP_LOG_INTERVAL]
    assert all(w["transport"] == "n" for w in warnings)
