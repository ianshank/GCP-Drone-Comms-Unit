import asyncio

import pytest

from meshsa import CotCodec, Envelope, MessageKind, TakMulticastTransport, transport_registry


class FakeDgram:
    def __init__(self):
        self.sent = []
        self.q: asyncio.Queue = asyncio.Queue()
        self.closed = False

    def sendto(self, data):
        self.sent.append(data)

    async def recv(self):
        return await self.q.get()

    def close(self):
        self.closed = True

    def push(self, d):
        self.q.put_nowait(d)


class FakeSleep:
    def __init__(self):
        self.calls = []

    async def __call__(self, secs):
        self.calls.append(secs)


def _cot_pli(uid="remote-1"):
    return CotCodec().encode(
        Envelope(
            msg_id="x",
            ts=1_700_000_000.0,
            source_uid=uid,
            kind=MessageKind.PLI,
            payload={"node": {"callsign": "RMT"}, "position": {"lat": 10.0, "lon": 20.0}},
        )
    )


async def _wait(cond, tries=300):
    for _ in range(tries):
        if cond():
            return
        await asyncio.sleep(0)
    raise AssertionError("condition not met in time")


# ============================ multicast transport ============================
async def test_multicast_send_and_receive():
    io = FakeDgram()
    t = TakMulticastTransport(io_factory=lambda: io)
    await t.start()
    await t.send(b"<event/></event>")
    assert io.sent == [b"<event/></event>"]
    io.push(_cot_pli())
    got = await asyncio.wait_for(t.stream().__anext__(), timeout=1.0)
    assert got.startswith(b"<event")
    await t.stop()
    assert io.closed


async def test_multicast_send_before_start_raises():
    t = TakMulticastTransport(io_factory=lambda: FakeDgram())
    with pytest.raises(RuntimeError):
        await t.send(b"x")


async def test_multicast_ignores_empty_datagram():
    io = FakeDgram()
    t = TakMulticastTransport(io_factory=lambda: io)
    await t.start()
    io.push(b"")  # falsy -> skipped
    io.push(_cot_pli())  # delivered
    got = await asyncio.wait_for(t.stream().__anext__(), timeout=1.0)
    assert got.startswith(b"<event")
    await t.stop()


async def test_multicast_stop_without_start_safe():
    t = TakMulticastTransport(io_factory=lambda: FakeDgram())
    await t.stop()


class RaiseOnceDgram(FakeDgram):
    """A FakeDgram whose first recv() raises, to exercise the recovery path."""

    def __init__(self):
        super().__init__()
        self._raised = False

    async def recv(self):
        if not self._raised:
            self._raised = True
            raise OSError("multicast recv boom")
        return await super().recv()


async def test_multicast_recovers_after_recv_error():
    # First socket errors on recv; the loop must close it, back off, rebuild via
    # the factory, and keep ingesting on the healthy second socket.
    bad, good = RaiseOnceDgram(), FakeDgram()
    ios = [bad, good]
    sleep = FakeSleep()
    t = TakMulticastTransport(io_factory=lambda: ios.pop(0), sleep=sleep)
    await t.start()
    await _wait(lambda: bad.closed and t.reconnects == 1)  # errored socket closed + rebuilt
    good.push(_cot_pli())
    got = await asyncio.wait_for(t.stream().__anext__(), timeout=1.0)
    assert got.startswith(b"<event")
    assert sleep.calls  # backoff slept before rebuilding
    await t.stop()
    assert good.closed


class RaiseAlwaysDgram(FakeDgram):
    """recv() always raises — used to drive the persistent-failure path."""

    async def recv(self):
        raise OSError("multicast down")


async def test_multicast_recv_loop_exits_on_stop_flag_during_backoff():
    box = {}

    async def flip(_secs):
        box["t"]._stopping = True  # stop arrives while backing off -> loop breaks

    t = TakMulticastTransport(io_factory=lambda: RaiseAlwaysDgram(), sleep=flip)
    box["t"] = t
    await t.start()
    await _wait(lambda: t._task.done())  # recv error -> backoff -> stop flag -> exit
    assert t.reconnects == 0  # never rebuilt; broke out after the stop flag
    await t.stop()


class CloseFailDgram(RaiseOnceDgram):
    """First recv() raises and close() also raises, to exercise close best-effort."""

    def close(self):
        raise OSError("close boom")


async def test_multicast_close_error_swallowed_during_recovery():
    ios = [CloseFailDgram(), FakeDgram()]
    t = TakMulticastTransport(io_factory=lambda: ios.pop(0), sleep=FakeSleep())
    await t.start()
    await _wait(lambda: t.reconnects == 1)  # close raised but was swallowed; rebuilt anyway
    await t.stop()


async def test_multicast_survives_factory_raising_during_rebuild():
    # The interface is still hard-down when the loop tries to rebuild: the first
    # socket errors on recv, and the *next* factory call raises (bind /
    # IP_ADD_MEMBERSHIP failing). An unguarded rebuild would kill the recv task
    # forever; instead the loop must back off and retry the factory, then ingest
    # once a healthy socket is finally returned.
    good = FakeDgram()
    attempts = {"n": 0}

    def factory():
        attempts["n"] += 1
        if attempts["n"] == 1:
            return RaiseOnceDgram()  # first socket: recv() raises once
        if attempts["n"] == 2:
            raise OSError("iface still down")  # rebuild attempt fails in the factory
        return good  # third attempt succeeds

    sleep = FakeSleep()
    t = TakMulticastTransport(io_factory=factory, sleep=sleep)
    await t.start()
    await _wait(lambda: t.reconnects == 1)  # survived the failed rebuild and eventually rebuilt
    assert attempts["n"] == 3  # factory was retried after it raised
    good.push(_cot_pli())
    got = await asyncio.wait_for(t.stream().__anext__(), timeout=1.0)
    assert got.startswith(b"<event")
    await t.stop()


async def test_multicast_joins_on_start_and_leaves_on_stop():
    # Transport-level group join/leave: io built on start, closed on stop.
    io = FakeDgram()
    made = {"n": 0}

    def factory():
        made["n"] += 1
        return io

    t = TakMulticastTransport(io_factory=factory)
    assert made["n"] == 0  # no group join before start
    await t.start()
    assert made["n"] == 1 and not io.closed  # joined exactly once
    await t.stop()
    assert io.closed  # left the group


# ============================ registry ============================
def test_tak_multicast_registered():
    assert transport_registry.has("tak_multicast")


def test_tak_multicast_registry_factory_creates():
    mc = transport_registry.create("tak_multicast", name="m", io_factory=lambda: FakeDgram())
    assert isinstance(mc, TakMulticastTransport)


def test_tak_multicast_string_port():
    # Multicast transport accepts string port
    t_mc = TakMulticastTransport(port="6970", io_factory=lambda: FakeDgram())
    assert t_mc._port == 6970
