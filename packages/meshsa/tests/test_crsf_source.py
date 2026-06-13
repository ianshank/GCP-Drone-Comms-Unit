import asyncio
import struct

import pytest
from conftest import FakeClock

from meshsa import CrsfSourceTransport, TelemetryCodec, transport_registry
from meshsa.fpv.config import CrsfLinkSettings
from meshsa.fpv.crsf.frame import CrsfFrame, CrsfFrameType
from meshsa.fpv.crsf.link import CrsfLink


def _gps_wire(*, lat: int = 377749000, lon: int = -1224194000, alt_raw: int = 1120) -> bytes:
    """On-wire CRSF GPS frame (37.7749, -122.4194, 120 m after the offset)."""
    payload = struct.pack(">iiHHHB", lat, lon, 123, 18000, alt_raw, 9)
    return CrsfFrame(addr=0xC8, type=CrsfFrameType.GPS, payload=payload).to_bytes()


def _link_stats_wire() -> bytes:
    """On-wire LINK_STATISTICS frame — a non-GPS telemetry type (no air track)."""
    payload = struct.pack(">BBBbBBBBBb", 70, 80, 99, -5, 1, 6, 3, 60, 100, 8)
    return CrsfFrame(addr=0xC8, type=CrsfFrameType.LINK_STATISTICS, payload=payload).to_bytes()


class FakeSerial:
    """A non-blocking ``CrsfSerial`` that yields each chunk once, then b''."""

    def __init__(self, *chunks: bytes) -> None:
        self._chunks = list(chunks)
        self.closed = False

    def read(self, size: int) -> bytes:
        return self._chunks.pop(0) if self._chunks else b""

    def write(self, data: bytes) -> int:  # pragma: no cover - source never transmits
        return len(data)

    def close(self) -> None:
        self.closed = True


class BoomSerial(FakeSerial):
    def read(self, size: int) -> bytes:
        raise RuntimeError("serial dropped")


def _link(*chunks: bytes, serial_cls: type[FakeSerial] = FakeSerial) -> CrsfLink:
    return CrsfLink(CrsfLinkSettings(), serial=serial_cls(*chunks))


async def _wait(cond, tries: int = 400) -> None:
    for _ in range(tries):
        if cond():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("condition not met in time")


def test_registered_in_transport_registry():
    assert transport_registry.has("crsf_source")
    t = transport_registry.create("crsf_source", name="x", link=_link())
    assert isinstance(t, CrsfSourceTransport)


async def test_gps_frame_becomes_air_track_and_ignores_non_gps():
    # One read carries a LINK_STATISTICS frame (ignored by the air-track seam)
    # followed by a GPS frame (the only type that yields a position).
    t = CrsfSourceTransport(
        name="uav",
        link=_link(_link_stats_wire() + _gps_wire()),
        source_uid="uav-1",
        callsign="UAV1",
        clock=FakeClock(),
        poll_interval_s=0.01,
    )
    await t.start()
    try:
        frame = await asyncio.wait_for(t.stream().__anext__(), timeout=2.0)
    finally:
        await t.stop()

    env = TelemetryCodec().decode(frame)
    assert env.source_uid == "uav-1"
    assert env.msg_id == "uav-1:1"
    assert env.payload["node"]["callsign"] == "UAV1"
    assert env.payload["position"]["lat"] == pytest.approx(37.7749)
    assert env.payload["position"]["lon"] == pytest.approx(-122.4194)
    assert env.payload["position"]["hae"] == pytest.approx(120.0)


async def test_reader_stops_on_poll_error():
    link = _link(serial_cls=BoomSerial)
    t = CrsfSourceTransport(name="uav", link=link, poll_interval_s=0.01)
    await t.start()
    await _wait(lambda: t._thread is not None and not t._thread.is_alive())
    await t.stop()


async def test_send_is_noop():
    t = CrsfSourceTransport(name="uav", link=_link())
    assert await t.send(b"x") is None


async def test_stop_before_start_is_safe():
    t = CrsfSourceTransport(name="uav")  # never started, no link injected
    await t.stop()  # link is None and thread is None — both no-op branches


async def test_stop_closes_link():
    serial = FakeSerial(_gps_wire())
    link = CrsfLink(CrsfLinkSettings(), serial=serial)
    t = CrsfSourceTransport(name="uav", link=link, poll_interval_s=0.01)
    await t.start()
    await t.stop()
    assert serial.closed
