import asyncio

import pytest

from meshsa import MeshtasticTransport, transport_registry


class FakeIface:
    def __init__(self):
        self.sent = []
        self.closed = False

    def sendData(self, data, **kw):
        self.sent.append((data, kw))

    def close(self):
        self.closed = True


class SendFailIface(FakeIface):
    def sendData(self, data, **kw):
        raise ConnectionError("send fail")


class CloseFailIface(FakeIface):
    def close(self):
        raise OSError("close fail")


class ScriptedFactory:
    def __init__(self, ifaces, fail_times=0):
        self._ifaces = list(ifaces)
        self.calls = 0
        self._fail = fail_times

    def __call__(self):
        self.calls += 1
        if self._fail > 0:
            self._fail -= 1
            raise ConnectionError("connect fail")
        return self._ifaces.pop(0)


class FakePub:
    def __init__(self):
        self.subs: dict[str, list] = {}

    def subscribe(self, fn, topic):
        self.subs.setdefault(topic, []).append(fn)

    def unsubscribe(self, fn, topic):
        lst = self.subs.get(topic, [])
        if fn in lst:
            lst.remove(fn)

    def emit(self, topic, **kw):
        for fn in list(self.subs.get(topic, [])):
            fn(**kw)


class FakeSleep:
    def __init__(self):
        self.calls = []

    async def __call__(self, secs):
        self.calls.append(secs)


def _make(factory_or_iface, pub, **kw):
    fac = (
        factory_or_iface
        if callable(factory_or_iface) and not isinstance(factory_or_iface, FakeIface)
        else (lambda: factory_or_iface)
    )
    return MeshtasticTransport(
        name="lora",
        interface_factory=fac,
        subscribe=pub.subscribe,
        unsubscribe=pub.unsubscribe,
        **kw,
    )


async def _wait(cond, tries=300):
    for _ in range(tries):
        if cond():
            return
        await asyncio.sleep(0)
    raise AssertionError("condition not met in time")


# ---- core send/receive ----
async def test_send_uses_configured_portnum_and_dest():
    iface, pub = FakeIface(), FakePub()
    t = _make(iface, pub, portnum=256, destination="^all", channel_index=2, sleep=FakeSleep())
    await t.start()
    await t.send(b"payload")
    data, kw = iface.sent[0]
    assert data == b"payload" and kw["portNum"] == 256
    assert kw["destinationId"] == "^all" and kw["channelIndex"] == 2
    await t.stop()
    assert iface.closed


async def test_receive_matching_portnum_is_ingested():
    iface, pub = FakeIface(), FakePub()
    t = _make(iface, pub, portnum=256, sleep=FakeSleep())
    await t.start()
    pub.emit(
        "meshtastic.receive",
        packet={"decoded": {"portnum": 256, "payload": b"hello"}},
        interface=iface,
    )
    got = await asyncio.wait_for(t.stream().__anext__(), timeout=1.0)
    assert got == b"hello"
    await t.stop()


async def test_receive_filters_other_portnum_and_empty():
    iface, pub = FakeIface(), FakePub()
    t = _make(iface, pub, portnum=256, sleep=FakeSleep())
    await t.start()
    pub.emit("meshtastic.receive", packet={"decoded": {"portnum": 1, "payload": b"x"}})
    pub.emit("meshtastic.receive", packet={"decoded": {"portnum": 256}})
    pub.emit("meshtastic.receive", packet=None)
    await asyncio.sleep(0.05)
    assert t._inbox.empty()
    await t.stop()


async def test_receive_accepts_portnum_name():
    iface, pub = FakeIface(), FakePub()
    t = _make(iface, pub, portnum=256, portnum_name="PRIVATE_APP", sleep=FakeSleep())
    await t.start()
    pub.emit(
        "meshtastic.receive", packet={"decoded": {"portnum": "PRIVATE_APP", "payload": b"named"}}
    )
    got = await asyncio.wait_for(t.stream().__anext__(), timeout=1.0)
    assert got == b"named"
    await t.stop()


async def test_send_before_start_raises():
    t = _make(FakeIface(), FakePub())
    with pytest.raises(RuntimeError):
        await t.send(b"x")


async def test_receive_before_start_is_dropped():
    t = _make(FakeIface(), FakePub(), portnum=256)
    t._on_receive(packet={"decoded": {"portnum": 256, "payload": b"x"}})  # loop None
    assert t._inbox.empty()


def test_on_lost_before_start_is_noop():
    t = _make(FakeIface(), FakePub())
    t._on_lost()  # loop/_lost None -> no error


async def test_stop_without_start_safe():
    t = _make(FakeIface(), FakePub())
    await t.stop()  # task None / not subscribed / iface None


def test_registry_factory_builds_with_injection():
    iface, pub = FakeIface(), FakePub()
    t = transport_registry.create(
        "meshtastic",
        name="lora",
        interface_factory=lambda: iface,
        subscribe=pub.subscribe,
        unsubscribe=pub.unsubscribe,
    )
    assert isinstance(t, MeshtasticTransport) and t.name == "lora"


# ---- reconnect / backoff ----
async def test_reconnects_after_connection_lost():
    i1, i2 = FakeIface(), FakeIface()
    fac, pub = ScriptedFactory([i1, i2]), FakePub()
    t = _make(fac, pub, sleep=FakeSleep())
    await t.start()  # factory #1 -> i1
    pub.emit("meshtastic.connection.lost")  # device drop
    await _wait(lambda: fac.calls >= 2)  # supervisor closes i1, rebuilds -> i2
    assert i1.closed and fac.calls == 2
    assert t.reconnects == 1  # one supervisor-driven reconnection
    await t.stop()


async def test_backoff_on_connect_failure():
    sl = FakeSleep()
    fac, pub = ScriptedFactory([FakeIface()], fail_times=4), FakePub()
    t = _make(fac, pub, sleep=sl, backoff_initial_s=1.0, backoff_max_s=3.0, backoff_factor=2.0)
    await t.start()  # initial connect fails
    await _wait(lambda: fac.calls >= 5)
    assert sl.calls == [1.0, 2.0, 3.0]  # grows then caps
    assert fac.calls == 5
    await t.stop()


async def test_no_reconnect_stops_after_lost():
    i1 = FakeIface()
    fac, pub = ScriptedFactory([i1]), FakePub()
    t = _make(fac, pub, reconnect=False)
    await t.start()
    pub.emit("meshtastic.connection.lost")
    await _wait(lambda: t._task.done())
    assert i1.closed and fac.calls == 1
    await t.send(b"x")  # iface None -> drop (no raise)
    await t.stop()


async def test_initial_connect_failure_raises_without_reconnect():
    fac, pub = ScriptedFactory([], fail_times=1), FakePub()
    t = _make(fac, pub, reconnect=False)
    with pytest.raises(ConnectionError):
        await t.start()
    assert pub.subs.get("meshtastic.receive") == []  # subscriptions torn down


async def test_send_swallows_error():
    fac, pub = ScriptedFactory([SendFailIface()]), FakePub()
    t = _make(fac, pub, sleep=FakeSleep())
    await t.start()
    await t.send(b"x")  # sendData raises -> swallowed
    await t.stop()


async def test_close_error_swallowed_on_stop():
    fac, pub = ScriptedFactory([CloseFailIface()]), FakePub()
    t = _make(fac, pub, sleep=FakeSleep())
    await t.start()
    await t.stop()  # close raises -> swallowed


async def test_supervisor_exits_on_stop_flag():
    box = {}

    async def flip(secs):
        box["t"]._stopping = True

    fac, pub = ScriptedFactory([], fail_times=99), FakePub()
    t = _make(fac, pub, reconnect=True, sleep=flip)
    box["t"] = t
    await t.start()
    await _wait(lambda: t._task.done())
    assert t._task.done()
    await t.stop()


# ---- mesh device provisioning (Gap A) ----
async def test_provisioner_called_with_mesh_on_start():
    iface, pub = FakeIface(), FakePub()
    seen = []
    t = _make(
        iface,
        pub,
        sleep=FakeSleep(),
        mesh={"region": "EU", "channel": "ops", "psk": None, "freq_khz": 906500},
        provision=lambda dev, mesh: seen.append((dev, mesh)),
    )
    await t.start()
    assert len(seen) == 1
    dev, mesh = seen[0]
    assert dev is iface
    assert mesh["region"] == "EU" and mesh["freq_khz"] == 906500
    await t.stop()


async def test_provisioner_not_called_without_mesh():
    iface, pub = FakeIface(), FakePub()
    seen = []
    t = _make(iface, pub, sleep=FakeSleep(), provision=lambda dev, mesh: seen.append(dev))
    await t.start()
    assert seen == []  # no mesh configured -> provisioning skipped
    await t.stop()


async def test_provisioner_reapplied_after_reconnect():
    # A rebuilt interface must be re-provisioned, not left on its boot config.
    i1, i2 = FakeIface(), FakeIface()
    fac, pub = ScriptedFactory([i1, i2]), FakePub()
    seen = []
    t = _make(
        fac,
        pub,
        sleep=FakeSleep(),
        mesh={"region": "EU"},
        provision=lambda dev, mesh: seen.append(dev),
    )
    await t.start()  # provisions i1
    pub.emit("meshtastic.connection.lost")  # drop -> supervisor rebuilds -> i2
    await _wait(lambda: fac.calls >= 2)
    await _wait(lambda: seen == [i1, i2])
    assert seen == [i1, i2]
    await t.stop()


async def test_receive_full_inbox_counts_drop():
    # The receive path must funnel through the shared drop-counter, not raise
    # QueueFull in the loop callback.
    iface, pub = FakeIface(), FakePub()
    t = _make(iface, pub, sleep=FakeSleep(), queue_maxsize=1)
    await t.start()
    for payload in (b"a", b"b"):  # 2nd overflows the 1-slot inbox
        pub.emit(
            "meshtastic.receive",
            packet={"decoded": {"portnum": 256, "payload": payload}},
            interface=iface,
        )
    await _wait(lambda: t.dropped_inbox_full >= 1)
    assert t.dropped_inbox_full == 1
    await t.stop()


# ---- default provisioner control flow (fakes for the device API) ----
class _FakeNode:
    def __init__(self):
        self.localConfig = type("_C", (), {"lora": type("_L", (), {"region": None})()})()
        self.written = []

    def writeConfig(self, name):
        self.written.append(name)


def test_default_provisioner_applies_region_and_logs_extras():
    from meshsa.transports.meshtastic_radio import _default_provisioner

    iface = type("_I", (), {"localNode": _FakeNode()})()
    _default_provisioner(iface, {"region": "EU", "channel": "ops", "psk": None, "freq_khz": 906500})
    assert iface.localNode.localConfig.lora.region == "EU"
    assert iface.localNode.written == ["lora"]


def test_default_provisioner_no_localnode_is_safe():
    from meshsa.transports.meshtastic_radio import _default_provisioner

    _default_provisioner(type("_I", (), {"localNode": None})(), {"region": "EU"})  # no raise


def test_default_provisioner_no_region_skips_write():
    from meshsa.transports.meshtastic_radio import _default_provisioner

    iface = type("_I", (), {"localNode": _FakeNode()})()
    _default_provisioner(iface, {"region": None, "channel": None, "psk": None, "freq_khz": None})
    assert iface.localNode.written == []


def test_construct_does_not_resolve_pubsub(monkeypatch):
    # pypubsub is resolved lazily in start(), not __init__, so a transport can be
    # built (e.g. for config validation in build_node) without the optional dep.
    import meshsa.transports.meshtastic_radio as mr

    def _boom():  # pragma: no cover - must never be called at construction
        raise AssertionError("pypubsub resolved at construction")

    monkeypatch.setattr(mr, "_default_pubsub", _boom)
    transport = mr.MeshtasticTransport(name="lora")
    assert transport.name == "lora"
    assert transport._subscribe is None and transport._unsubscribe is None
