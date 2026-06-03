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
