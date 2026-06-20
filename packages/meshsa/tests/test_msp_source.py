import asyncio

import pytest
from conftest import FakeClock

from meshsa import MspSourceTransport, TelemetryCodec, transport_registry


class FakeBoard:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class CloseRaiseBoard(FakeBoard):
    def close(self) -> None:
        raise OSError("close failed")


def _fix_poll(*fixes):
    """Return a poll() that yields the given fixes once each, then None forever."""
    seq = list(fixes)

    def poll(_board):
        return seq.pop(0) if seq else None

    return poll


async def _wait(cond, tries: int = 400) -> None:
    for _ in range(tries):
        if cond():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("condition not met in time")


def test_registered_in_transport_registry():
    assert transport_registry.has("msp_source")
    t = transport_registry.create("msp_source", name="x", board=FakeBoard(), poll=_fix_poll())
    assert isinstance(t, MspSourceTransport)


async def test_polls_gps_fix_into_telemetry_frame():
    board = FakeBoard()
    t = MspSourceTransport(
        name="fc",
        board=board,
        poll=_fix_poll({"lat": 377749000, "lon": -1224194000, "alt": 120}),
        source_uid="fc-1",
        callsign="FC1",
        clock=FakeClock(),
        poll_interval_s=0.01,
    )
    await t.start()
    try:
        frame = await asyncio.wait_for(t.stream().__anext__(), timeout=2.0)
    finally:
        await t.stop()

    env = TelemetryCodec().decode(frame)
    assert env.source_uid == "fc-1"
    assert env.msg_id == "fc-1:1"
    assert env.payload["node"]["callsign"] == "FC1"
    assert env.payload["position"]["lat"] == pytest.approx(37.7749)
    assert env.payload["position"]["lon"] == pytest.approx(-122.4194)
    assert env.payload["position"]["hae"] == pytest.approx(120.0)
    assert board.closed


async def test_no_fix_yields_no_frame_then_recovers():
    # First poll returns None (no GPS fix) — exercises the skip branch — then a fix.
    board = FakeBoard()
    t = MspSourceTransport(
        name="fc",
        board=board,
        poll=_fix_poll(None, {"lat": 10000000, "lon": 20000000, "alt": 0}),
        poll_interval_s=0.01,
    )
    await t.start()
    try:
        frame = await asyncio.wait_for(t.stream().__anext__(), timeout=2.0)
    finally:
        await t.stop()
    assert TelemetryCodec().decode(frame).payload["position"]["lat"] == pytest.approx(1.0)


async def test_reader_stops_on_poll_error():
    def boom(_board):
        raise RuntimeError("serial dropped")

    board = FakeBoard()
    t = MspSourceTransport(name="fc", board=board, poll=boom, poll_interval_s=0.01)
    await t.start()
    await _wait(lambda: t._thread is not None and not t._thread.is_alive())
    await t.stop()
    assert board.closed


async def test_send_is_noop():
    t = MspSourceTransport(name="fc", board=FakeBoard(), poll=_fix_poll())
    assert await t.send(b"x") is None


async def test_stop_before_start_is_safe():
    t = MspSourceTransport(name="fc")  # never started, no board injected
    await t.stop()  # board is None and thread is None — both no-op branches


async def test_stop_handles_close_error():
    t = MspSourceTransport(
        name="fc", board=CloseRaiseBoard(), poll=_fix_poll(), poll_interval_s=0.01
    )
    await t.start()
    await t.stop()  # close() raises; transport swallows it


async def test_stop_with_board_lacking_close():
    # A board object with no close() method — exercises the not-callable branch.
    t = MspSourceTransport(name="fc", board=object(), poll=_fix_poll(), poll_interval_s=0.01)
    await t.start()
    await t.stop()
