import asyncio
import json

import pytest
from conftest import FakeClock

from meshsa import MspSourceTransport, TelemetryCodec, transport_registry
from meshsa.transports.msp_source import build_telemetry_frame


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


async def test_fallback_position_used_when_no_fix():
    # A GPS-less bench FC: poll never returns a fix, but a fallback keeps it on the map.
    board = FakeBoard()
    t = MspSourceTransport(
        name="fc",
        board=board,
        poll=_fix_poll(None),  # no fix, ever
        source_uid="fc-1",
        callsign="FC1",
        clock=FakeClock(),
        fallback_lat=37.0,
        fallback_lon=-122.0,
        fallback_hae=5.0,
        poll_interval_s=0.01,
    )
    await t.start()
    try:
        frame = await asyncio.wait_for(t.stream().__anext__(), timeout=2.0)
    finally:
        await t.stop()
    pos = TelemetryCodec().decode(frame).payload["position"]
    assert pos["lat"] == pytest.approx(37.0)  # fallback is in degrees, NOT coord-scaled
    assert pos["lon"] == pytest.approx(-122.0)
    assert pos["hae"] == pytest.approx(5.0)


async def test_telemetry_sample_renders_remarks():
    # No GPS fix, but battery/RSSI/attitude telemetry + a fallback -> a track with remarks.
    board = FakeBoard()
    t = MspSourceTransport(
        name="fc",
        board=board,
        poll=_fix_poll({"vbat": 11.84, "rssi": 1023, "amperage": 2.5, "roll": 2.0, "yaw": 90}),
        fallback_lat=1.0,
        fallback_lon=2.0,
        poll_interval_s=0.01,
    )
    await t.start()
    try:
        frame = await asyncio.wait_for(t.stream().__anext__(), timeout=2.0)
    finally:
        await t.stop()
    env = TelemetryCodec().decode(frame)
    assert env.payload["position"]["lat"] == pytest.approx(1.0)
    assert env.payload["remarks"] == "VBAT 11.8V CUR 2.5A RSSI 1023 ROLL 2 YAW 90"


async def test_fix_with_remarks_and_unformattable_field():
    # A real fix wins over the fallback; a non-numeric telemetry value is skipped, not fatal.
    board = FakeBoard()
    t = MspSourceTransport(
        name="fc",
        board=board,
        poll=_fix_poll({"lat": 10000000, "lon": 20000000, "alt": 7, "vbat": "n/a", "pitch": -1}),
        fallback_lat=99.0,
        fallback_lon=99.0,
        poll_interval_s=0.01,
    )
    await t.start()
    try:
        frame = await asyncio.wait_for(t.stream().__anext__(), timeout=2.0)
    finally:
        await t.stop()
    env = TelemetryCodec().decode(frame)
    assert env.payload["position"]["lat"] == pytest.approx(1.0)  # the fix, not the fallback
    assert env.payload["remarks"] == "PITCH -1"  # vbat="n/a" skipped


def test_build_telemetry_frame_fix_fallback_and_seq():
    # A GPS fix is scaled by coord_scale; remarks are rendered; msg_id uses the given seq.
    frame = build_telemetry_frame(
        {"lat": 377749000, "lon": -1224194000, "alt": 12, "vbat": 11.84},
        seq=7,
        source_uid="fc-1",
        callsign="FC1",
        now=1234.0,
    )
    assert frame is not None
    obj = json.loads(frame)
    assert obj["msg_id"] == "fc-1:7"
    assert obj["lat"] == pytest.approx(37.7749)
    assert obj["remarks"] == "VBAT 11.8V"

    # No fix + a fallback -> frame at the fallback (degrees, not coord-scaled).
    fb = build_telemetry_frame(
        {"rssi": 1023},
        seq=1,
        source_uid="x",
        callsign="x",
        now=0.0,
        fallback_lat=37.0,
        fallback_lon=-122.0,
        fallback_hae=5.0,
    )
    assert fb is not None and json.loads(fb)["lat"] == pytest.approx(37.0)

    # No fix + no fallback -> nothing.
    assert build_telemetry_frame(None, seq=1, source_uid="x", callsign="x", now=0.0) is None


async def test_no_fix_no_fallback_emits_nothing():
    # The original behaviour: no fix and no fallback -> no frame at all.
    board = FakeBoard()
    t = MspSourceTransport(name="fc", board=board, poll=_fix_poll(None), poll_interval_s=0.01)
    await t.start()
    try:
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(t.stream().__anext__(), timeout=0.2)
    finally:
        await t.stop()


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
