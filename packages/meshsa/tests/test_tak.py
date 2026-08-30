import asyncio

import pytest

from meshsa import (
    CotCodec,
    Envelope,
    JsonCodec,
    LoopbackBus,
    LoopbackTransport,
    MessageKind,
    NodeConfig,
    Position,
    TakTcpTransport,
    build_node,
    transport_registry,
)
from meshsa.transports.tak import CotFramer, _build_ssl_context


# ============================ TLS context ============================
def test_build_ssl_context_clear_error_on_missing_cert_files(tmp_path):
    missing = str(tmp_path / "nope.pem")
    with pytest.raises(FileNotFoundError, match="tls_ca_cert not found"):
        _build_ssl_context(ca_cert=missing, client_cert=None, client_key=None, verify=True)
    real = tmp_path / "ca.pem"
    real.write_text("x", encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="tls_client_cert not found"):
        _build_ssl_context(ca_cert=None, client_cert=missing, client_key=str(real), verify=True)


def test_build_ssl_context_no_certs_is_fine():
    # No cert paths configured -> no file checks, default verifying context.
    ctx = _build_ssl_context(ca_cert=None, client_cert=None, client_key=None, verify=True)
    assert ctx.verify_mode.name == "CERT_REQUIRED"


def test_build_ssl_context_requires_cert_when_key_set(tmp_path):
    key = tmp_path / "client.key"
    key.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="tls_client_cert is required when tls_client_key"):
        _build_ssl_context(ca_cert=None, client_cert=None, client_key=str(key), verify=True)


def test_require_file_rejects_a_directory(tmp_path):
    # A configured cert path that resolves to a directory (not a regular file) must be
    # refused clearly, distinct from "not found" (the path does exist) and from the
    # unreadable-permissions case below.
    from meshsa.transports.tak import _require_file

    directory = tmp_path / "ca_dir"
    directory.mkdir()
    with pytest.raises(FileNotFoundError, match="tls_ca_cert is not a regular file"):
        _require_file("tls_ca_cert", str(directory))


def test_require_file_distinguishes_unreadable_from_missing(tmp_path):
    import os as _os

    from meshsa.transports.tak import _require_file

    if hasattr(_os, "geteuid") and _os.geteuid() == 0:
        pytest.skip("root bypasses file permission checks")
    if _os.name == "nt":
        pytest.skip("Windows os.access(R_OK) does not respect chmod 000")
    f = tmp_path / "ca.pem"
    f.write_text("x", encoding="utf-8")
    _os.chmod(f, 0o000)
    try:
        # exists but unreadable -> PermissionError, not a misleading FileNotFoundError
        with pytest.raises(PermissionError, match="not readable"):
            _require_file("tls_ca_cert", str(f))
    finally:
        _os.chmod(f, 0o644)  # restore so tmp cleanup can remove it


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


class _FixedClock:
    """now() never advances on its own — pacing math is fully controlled here."""

    def __init__(self, t: float = 0.0):
        self.t = t

    def now(self) -> float:
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
async def test_pacing_delays_sends_after_the_burst():
    reader, writer = QueueReader(), FakeWriter()
    clock = _FixedClock()
    sleep = FakeSleep()
    t = TakTcpTransport(
        connector=lambda: _conn(reader, writer),
        pacing=True,
        pacing_rate_hz=10.0,
        pacing_burst=1,
        clock=clock,
        sleep=sleep,
    )
    await t.start()
    await t.send(b"<a/></event>")  # initial burst token -> no pacing wait
    await t.send(b"<b/></event>")  # bucket empty -> paced one interval (0.1 s)
    await t.stop()
    assert sleep.calls == [pytest.approx(0.1)]
    assert writer.buf == b"<a/></event><b/></event>"


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


# ============================ registry ============================
def test_tak_tcp_registered():
    assert transport_registry.has("tak_tcp")


def test_tak_tcp_registry_factory_creates():
    tcp = transport_registry.create(
        "tak_tcp", name="t", connector=lambda: _conn(QueueReader(), FakeWriter())
    )
    assert isinstance(tcp, TakTcpTransport)


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


def test_tak_tcp_string_ports():
    # TCP transport resolved endpoint with string port
    t_tcp = TakTcpTransport(
        host="127.0.0.1", port="8090", connector=lambda: _conn(QueueReader(), FakeWriter())
    )
    assert t_tcp.port == 8090

    # TCP transport with schemed host
    t_tcp_scheme = TakTcpTransport(
        host="tcp://127.0.0.1:8091", connector=lambda: _conn(QueueReader(), FakeWriter())
    )
    assert t_tcp_scheme.port == 8091
