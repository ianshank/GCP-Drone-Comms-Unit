import asyncio
import queue

import pytest
from conftest import FakeClock

from meshsa import MavlinkSourceTransport, TelemetryCodec, transport_registry


class FakeMsg:
    """Stand-in for a pymavlink GLOBAL_POSITION_INT (degE7 lat/lon, mm alt)."""

    def __init__(self, lat: int, lon: int, alt: int) -> None:
        self.lat = lat
        self.lon = lon
        self.alt = alt


class FakeConn:
    def __init__(self) -> None:
        self._q: queue.Queue = queue.Queue()
        self.closed = False

    def feed(self, item) -> None:
        self._q.put(item)

    def recv_match(self, type=None, blocking=True, timeout=None):
        try:
            return self._q.get(timeout=timeout if timeout is not None else 0.05)
        except queue.Empty:
            return None  # idle/timeout

    def close(self) -> None:
        self.closed = True


class RaiseConn:
    def __init__(self) -> None:
        self.closed = False

    def recv_match(self, **_kw):
        raise ConnectionError("link error")

    def close(self) -> None:
        self.closed = True


class CloseRaiseConn(FakeConn):
    def close(self) -> None:
        raise OSError("close failed")


async def _wait(cond, tries: int = 400) -> None:
    for _ in range(tries):
        if cond():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("condition not met in time")


def test_registered_in_transport_registry():
    assert transport_registry.has("mavlink_source")
    t = transport_registry.create("mavlink_source", name="x", connection=FakeConn())
    assert isinstance(t, MavlinkSourceTransport)


async def test_reads_position_fix_into_telemetry_frame():
    conn = FakeConn()
    t = MavlinkSourceTransport(
        name="drone",
        connection=conn,
        source_uid="uav-1",
        callsign="UAV1",
        clock=FakeClock(),
        recv_timeout_s=0.05,
    )
    await t.start()
    conn.feed(FakeMsg(377749000, -1224194000, 100000))
    try:
        frame = await asyncio.wait_for(t.stream().__anext__(), timeout=2.0)
    finally:
        await t.stop()

    env = TelemetryCodec().decode(frame)
    assert env.source_uid == "uav-1"
    assert env.msg_id == "uav-1:1"
    assert env.ts == pytest.approx(1001.0)  # FakeClock first tick
    assert env.payload["position"]["lat"] == pytest.approx(37.7749)
    assert env.payload["position"]["lon"] == pytest.approx(-122.4194)
    assert env.payload["position"]["hae"] == pytest.approx(100.0)
    assert conn.closed


async def test_each_fix_gets_a_unique_msg_id():
    conn = FakeConn()
    t = MavlinkSourceTransport(
        name="drone", connection=conn, source_uid="uav-1", recv_timeout_s=0.05
    )
    await t.start()
    conn.feed(FakeMsg(0, 0, 0))
    conn.feed(FakeMsg(10000000, 20000000, 5000))
    try:
        gen = t.stream()
        f1 = await asyncio.wait_for(gen.__anext__(), timeout=2.0)
        f2 = await asyncio.wait_for(gen.__anext__(), timeout=2.0)
    finally:
        await t.stop()
    codec = TelemetryCodec()
    assert codec.decode(f1).msg_id == "uav-1:1"
    assert codec.decode(f2).msg_id == "uav-1:2"


async def test_reader_stops_on_recv_error():
    conn = RaiseConn()
    t = MavlinkSourceTransport(name="d", connection=conn, recv_timeout_s=0.05)
    await t.start()
    await _wait(lambda: t._thread is not None and not t._thread.is_alive())
    await t.stop()
    assert conn.closed


async def test_send_is_noop():
    t = MavlinkSourceTransport(name="d", connection=FakeConn())
    assert await t.send(b"anything") is None


async def test_stop_before_start_is_safe():
    t = MavlinkSourceTransport(name="d")  # no connection injected, never started
    await t.stop()  # conn is None and thread is None — both no-op branches


async def test_stop_handles_close_error():
    conn = CloseRaiseConn()
    t = MavlinkSourceTransport(name="d", connection=conn, recv_timeout_s=0.05)
    await t.start()
    await t.stop()  # close() raises; transport swallows it
