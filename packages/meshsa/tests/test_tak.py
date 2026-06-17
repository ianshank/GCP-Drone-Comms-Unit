import asyncio
import ssl

import pytest
import trustme

from meshsa import (
    CotCodec,
    Envelope,
    JsonCodec,
    LoopbackBus,
    LoopbackTransport,
    MessageKind,
    NodeConfig,
    Position,
    TakMulticastTransport,
    TakTcpTransport,
    build_node,
    transport_registry,
)
from meshsa.transports.tak import CotFramer, _build_ssl_context


# ============================ framer ============================
def test_framer_splits_concatenated_and_partial():
    f = CotFramer()
    assert f.feed(b"<event a><point/></eve") == []  # partial -> buffered
    out = f.feed(b"nt><event b></event>junk<event c></event>")
    assert out == [
        b"<event a><point/></event>",
        b"<event b></event>",
        b"<event c></event>",  # inter-event "junk" is resynced away
    ]


def test_framer_discards_stray_closing_tag():
    assert CotFramer().feed(b"</event>") == []  # no <event> start -> dropped


def test_framer_strips_leading_noise():
    assert CotFramer().feed(b"\n  <event x></event>") == [b"<event x></event>"]


# ============================ fakes ============================
class QueueReader:
    def __init__(self):
        self.q: asyncio.Queue = asyncio.Queue()

    async def read(self, n):
        return await self.q.get()

    def push(self, data):
        self.q.put_nowait(data)


class EofReader:
    async def read(self, n):
        return b""


class RaiseReader:
    async def read(self, n):
        raise ConnectionError("read fail")


class FakeWriter:
    def __init__(self):
        self.buf = b""
        self.closed = False

    def write(self, d):
        self.buf += d

    async def drain(self):
        pass

    def close(self):
        self.closed = True

    async def wait_closed(self):
        pass


class NoWaitWriter:
    def __init__(self):
        self.buf = b""
        self.closed = False

    def write(self, d):
        self.buf += d

    async def drain(self):
        pass

    def close(self):
        self.closed = True

    # intentionally no wait_closed()


class DrainFailWriter(FakeWriter):
    async def drain(self):
        raise ConnectionError("drain fail")


class CloseFailWriter(FakeWriter):
    def close(self):
        raise OSError("close fail")


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


class ScriptedConnector:
    """Yields (reader, writer) pairs in order; first `fail_times` calls raise."""

    def __init__(self, pairs, fail_times=0):
        self._pairs = list(pairs)
        self.calls = 0
        self._fail = fail_times

    async def __call__(self):
        self.calls += 1
        if self._fail > 0:
            self._fail -= 1
            raise ConnectionError("connect fail")
        return self._pairs.pop(0)


class FakeSleep:
    def __init__(self):
        self.calls = []

    async def __call__(self, secs):
        self.calls.append(secs)


class ManualClock:
    """Settable, non-advancing clock for deterministic pacing assertions."""

    def __init__(self, t=0.0):
        self.t = t

    def now(self):
        return self.t


def _conn(reader, writer):
    async def connect():
        return reader, writer

    return connect()


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


# ============================ TCP transport ============================
async def test_tcp_send_writes_with_delimiter():
    reader, writer = QueueReader(), FakeWriter()
    t = TakTcpTransport(connector=lambda: _conn(reader, writer), delimiter=b"\n", sleep=FakeSleep())
    await t.start()
    await t.send(b"<event/></event>")
    assert writer.buf.endswith(b"\n")
    reader.push(b"")
    await t.stop()
    assert writer.closed


async def test_tcp_receive_frames_and_ingests():
    reader, writer = QueueReader(), FakeWriter()
    t = TakTcpTransport(connector=lambda: _conn(reader, writer), sleep=FakeSleep())
    await t.start()
    reader.push(_cot_pli()[:20])  # partial
    reader.push(_cot_pli()[20:])  # completes the event
    got = await asyncio.wait_for(t.stream().__anext__(), timeout=1.0)
    assert got.startswith(b"<event")
    reader.push(b"")
    await t.stop()


async def test_tcp_send_before_start_raises():
    t = TakTcpTransport(connector=lambda: _conn(QueueReader(), FakeWriter()))
    with pytest.raises(RuntimeError):
        await t.send(b"x")


async def test_tcp_stop_without_start_safe():
    t = TakTcpTransport(connector=lambda: _conn(QueueReader(), FakeWriter()))
    await t.stop()  # task None / writer None branches


async def test_tcp_stop_writer_without_wait_closed():
    reader, writer = QueueReader(), NoWaitWriter()
    t = TakTcpTransport(connector=lambda: _conn(reader, writer), sleep=FakeSleep())
    await t.start()
    await t.stop()  # getattr(wait_closed) -> None branch
    assert writer.closed


async def test_tcp_reconnects_after_eof():
    r2 = QueueReader()
    conn = ScriptedConnector([(EofReader(), FakeWriter()), (r2, FakeWriter())])
    t = TakTcpTransport(connector=conn, sleep=FakeSleep())
    await t.start()  # connect #1 (EofReader) -> EOF
    await _wait(lambda: conn.calls >= 2)  # -> reconnect to #2
    r2.push(_cot_pli())
    got = await asyncio.wait_for(t.stream().__anext__(), timeout=1.0)
    assert got.startswith(b"<event")
    assert conn.calls == 2
    assert t.reconnects == 1  # one supervisor-driven reconnection
    await t.stop()


async def test_tcp_reconnects_after_read_error():
    conn = ScriptedConnector([(RaiseReader(), FakeWriter()), (QueueReader(), FakeWriter())])
    t = TakTcpTransport(connector=conn, sleep=FakeSleep())
    await t.start()
    await _wait(lambda: conn.calls >= 2)  # read error -> reconnect
    assert conn.calls == 2
    await t.stop()


async def test_tcp_backoff_grows_and_caps():
    sl = FakeSleep()
    conn = ScriptedConnector([(QueueReader(), FakeWriter())], fail_times=4)
    t = TakTcpTransport(
        connector=conn, sleep=sl, backoff_initial_s=1.0, backoff_max_s=3.0, backoff_factor=2.0
    )
    await t.start()  # initial connect fails -> supervisor retries
    await _wait(lambda: conn.calls >= 5)
    assert sl.calls == [1.0, 2.0, 3.0]  # grows then caps at max
    assert conn.calls == 5
    await t.stop()


async def test_tcp_no_reconnect_stops_on_eof():
    conn = ScriptedConnector([(EofReader(), FakeWriter())])
    t = TakTcpTransport(connector=conn, reconnect=False)
    await t.start()
    await _wait(lambda: t._task.done())  # EOF -> break (no reconnect)
    assert conn.calls == 1
    await t.send(b"x")  # writer None -> best-effort drop (no raise)
    await t.stop()


async def test_tcp_initial_connect_failure_raises_without_reconnect():
    conn = ScriptedConnector([], fail_times=1)
    t = TakTcpTransport(connector=conn, reconnect=False)
    with pytest.raises(ConnectionError):
        await t.start()


async def test_tcp_send_swallows_write_error():
    conn = ScriptedConnector([(QueueReader(), DrainFailWriter())])
    t = TakTcpTransport(connector=conn, sleep=FakeSleep())
    await t.start()
    await t.send(b"x")  # drain raises -> swallowed
    await t.stop()


async def test_tcp_close_error_swallowed_on_stop():
    conn = ScriptedConnector([(QueueReader(), CloseFailWriter())])
    t = TakTcpTransport(connector=conn, sleep=FakeSleep())
    await t.start()
    await t.stop()  # close raises -> swallowed


async def test_tcp_supervisor_exits_on_stop_flag():
    box = {}

    async def flip(secs):
        box["t"]._stopping = True

    conn = ScriptedConnector([], fail_times=99)
    t = TakTcpTransport(connector=conn, reconnect=True, sleep=flip)
    box["t"] = t
    await t.start()  # initial connect fails -> supervisor
    await _wait(lambda: t._task.done())  # connect fail -> sleep flips stop -> loop exits
    assert t._task.done()
    await t.stop()


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


# ============================ registry ============================
def test_tak_registered():
    assert transport_registry.has("tak_tcp")
    assert transport_registry.has("tak_multicast")


def test_tak_registry_factories_create():
    tcp = transport_registry.create(
        "tak_tcp", name="t", connector=lambda: _conn(QueueReader(), FakeWriter())
    )
    mc = transport_registry.create("tak_multicast", name="m", io_factory=lambda: FakeDgram())
    assert isinstance(tcp, TakTcpTransport)
    assert isinstance(mc, TakMulticastTransport)


# ================ END TO END: JSON mesh <-> CoT TAK bridge ================
async def test_e2e_json_mesh_cot_tak_bridge(clock, ids):
    bus = LoopbackBus()
    reader, writer = QueueReader(), FakeWriter()
    cfg = NodeConfig(
        uid="base",
        callsign="BASE",
        tier="base",
        transports=[
            {"name": "mesh", "type": "loopback"},
            {"name": "tak", "type": "tak_tcp", "codec": "cot"},
        ],
    )
    node = build_node(
        cfg,
        clock=clock,
        id_factory=ids,
        transport_kwargs={
            "mesh": {"bus": bus},
            "tak": {"connector": lambda: _conn(reader, writer), "sleep": FakeSleep()},
        },
    )
    peer = LoopbackTransport(name="peer", bus=bus)
    await node.start()

    # (1) locally-published position: JSON to the mesh, CoT to the TAK server
    await node.publish_position(Position(lat=37.0, lon=-122.0))
    mesh_json = await asyncio.wait_for(peer.stream().__anext__(), timeout=1.0)
    assert JsonCodec().decode(mesh_json).payload["position"]["lat"] == 37.0
    assert writer.buf.startswith(b"<event")

    # (2) CoT arriving from the TAK server is bridged to the mesh as JSON
    reader.push(_cot_pli("remote-1"))
    bridged = await asyncio.wait_for(peer.stream().__anext__(), timeout=1.0)
    out = JsonCodec().decode(bridged)
    assert out.kind == MessageKind.PLI
    assert out.source_uid == "remote-1"
    assert out.payload["position"]["lat"] == 10.0

    reader.push(b"")
    await node.stop()


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


# ============================ TLS ============================
@pytest.fixture
def tls_certs(tmp_path):
    """An ephemeral CA + client cert chain on disk (in-test, no committed PEM)."""
    ca = trustme.CA()
    leaf = ca.issue_cert("client.local")
    ca_path = tmp_path / "ca.pem"
    chain_path = tmp_path / "client.pem"  # combined key + cert chain
    ca.cert_pem.write_to_path(str(ca_path))
    leaf.private_key_and_cert_chain_pem.write_to_path(str(chain_path))
    return {"ca": str(ca_path), "chain": str(chain_path)}


def test_build_ssl_context_defaults_verify_and_check_hostname():
    ctx = _build_ssl_context()
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname is True


def test_build_ssl_context_verify_without_hostname_check():
    ctx = _build_ssl_context(check_hostname=False)
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname is False


def test_build_ssl_context_insecure_disables_verification():
    # check_hostname must be cleared before CERT_NONE or stdlib ssl raises.
    ctx = _build_ssl_context(verify=False)
    assert ctx.verify_mode == ssl.CERT_NONE
    assert ctx.check_hostname is False


def test_build_ssl_context_loads_ca_and_client_chain(tls_certs):
    ctx = _build_ssl_context(cafile=tls_certs["ca"], certfile=tls_certs["chain"])
    assert ctx.cert_store_stats()["x509"] >= 1  # CA trusted; client chain loaded w/o error


async def test_tls_injected_connector_wins():
    # tls=True but an explicit connector is injected -> no SSL context, no real socket.
    reader, writer = QueueReader(), FakeWriter()
    t = TakTcpTransport(tls=True, connector=lambda: _conn(reader, writer), sleep=FakeSleep())
    await t.start()
    await t.send(b"<event/></event>")
    assert writer.buf  # used the injected connector
    reader.push(b"")
    await t.stop()


def test_tls_builds_tls_connector(monkeypatch):
    captured = {}

    def fake_tls_connector(host, port, context, server_hostname):
        captured.update(host=host, port=port, context=context, server_hostname=server_hostname)
        return lambda: _conn(QueueReader(), FakeWriter())

    monkeypatch.setattr("meshsa.transports.tak._default_tls_connector", fake_tls_connector)
    TakTcpTransport(tls=True, host="fts.local", port=8089, tls_server_hostname="fts.local")
    assert captured["host"] == "fts.local"
    assert captured["port"] == 8089
    assert captured["server_hostname"] == "fts.local"
    assert isinstance(captured["context"], ssl.SSLContext)


def test_tls_bad_cert_fails_fast(tmp_path):
    # A missing cert raises at construction (fail-fast), not at start().
    with pytest.raises((FileNotFoundError, ssl.SSLError, OSError)):
        TakTcpTransport(tls=True, tls_certfile=str(tmp_path / "missing.pem"))


def test_default_plaintext_connector_when_no_tls_and_no_connector():
    # No injected connector and tls=False -> plaintext default connector is built
    # (closure only; no socket opened until start()).
    t = TakTcpTransport(host="10.0.0.1", port=8087)
    assert t._connector is not None


# ============================ pacing ============================
async def test_tcp_send_paces_between_frames():
    # A fixed clock means no virtual time passes between sends, so the second frame
    # waits the full minimum-hold; frames still go out in order.
    reader, writer = QueueReader(), FakeWriter()
    sl = FakeSleep()
    t = TakTcpTransport(
        connector=lambda: _conn(reader, writer),
        sleep=sl,
        pace_min_interval_s=0.5,
        clock=ManualClock(0.0),
    )
    await t.start()
    await t.send(b"<a></event>")  # first frame: no hold
    await t.send(b"<b></event>")  # second frame: full hold
    assert writer.buf == b"<a></event><b></event>"  # paced, not reordered/dropped
    assert sl.calls == [pytest.approx(0.5)]
    reader.push(b"")
    await t.stop()


async def test_tcp_send_unpaced_by_default():
    reader, writer = QueueReader(), FakeWriter()
    sl = FakeSleep()
    t = TakTcpTransport(connector=lambda: _conn(reader, writer), sleep=sl)
    assert t._pacer is None  # no pacing configured
    await t.start()
    await t.send(b"<a></event>")
    await t.send(b"<b></event>")
    assert sl.calls == []  # no minimum-hold sleeps
    reader.push(b"")
    await t.stop()


async def test_e2e_tls_option_plumbs_through_build_node(clock, ids):
    # The `tls` option round-trips through TransportConfig -> registry -> constructor;
    # the injected connector keeps it hermetic (no real TLS socket).
    bus = LoopbackBus()
    reader, writer = QueueReader(), FakeWriter()
    cfg = NodeConfig(
        uid="base",
        callsign="BASE",
        tier="base",
        transports=[
            {"name": "mesh", "type": "loopback"},
            {
                "name": "tak",
                "type": "tak_tcp",
                "codec": "cot",
                "options": {"tls": True, "port": 8089, "tls_verify": False},
            },
        ],
    )
    node = build_node(
        cfg,
        clock=clock,
        id_factory=ids,
        transport_kwargs={
            "mesh": {"bus": bus},
            "tak": {"connector": lambda: _conn(reader, writer), "sleep": FakeSleep()},
        },
    )
    await node.start()
    await node.publish_position(Position(lat=1.0, lon=2.0))
    assert writer.buf.startswith(b"<event")
    reader.push(b"")
    await node.stop()
