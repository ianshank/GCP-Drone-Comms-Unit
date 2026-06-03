from meshsa import LoopbackBus, LoopbackTransport, NullTransport


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
    await t._ingest(b"b")  # full -> dropped, counted
    assert t.dropped_inbox_full == 1
    assert t._inbox.qsize() == 1
