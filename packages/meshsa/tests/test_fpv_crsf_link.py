"""CrsfLink lifecycle, RC transmit, CRC accounting (Phase 0 / §5)."""

from __future__ import annotations

import pytest
from _fpv_helpers import FakeCrsfSerial, link_statistics_bytes

from meshsa.fpv.config import CrsfLinkSettings
from meshsa.fpv.crsf.frame import CrsfFrame, CrsfFrameType
from meshsa.fpv.crsf.rc import unpack_channels


def _link(**kw) -> tuple:
    fake = FakeCrsfSerial(echo=kw.pop("echo", False))
    from meshsa.fpv.crsf.link import CrsfLink

    link = CrsfLink(CrsfLinkSettings(**kw), serial=fake)
    return link, fake


def test_poll_and_send_require_open():
    from meshsa.fpv.crsf.link import CrsfLink

    # No serial injected and not opened -> the guard fires.
    link = CrsfLink(CrsfLinkSettings(), serial=None)
    with pytest.raises(RuntimeError, match="not open"):
        link.poll_inbound()
    with pytest.raises(RuntimeError, match="not open"):
        link.send_rc([1500])


def test_open_with_injected_serial_is_noop_and_close_idempotent():
    link, fake = _link()
    link.open()  # injected serial -> factory not used
    link.close()
    assert fake.closed is True
    link.close()  # idempotent


def test_send_rc_writes_decodable_frame():
    link, fake = _link(crsf_address=0xC8)
    link.open()
    link.send_rc([988, 2012, 1500, 1500])
    assert len(fake.written) == 1
    frame = CrsfFrame.from_bytes(fake.written[0])
    assert frame.addr == 0xC8
    assert frame.type == CrsfFrameType.RC_CHANNELS_PACKED
    ticks = unpack_channels(frame.payload, count=16)
    assert ticks[0] == 172  # 988us -> ticks_min
    assert ticks[1] == 1811  # 2012us -> ticks_max


def test_poll_returns_telemetry_and_counts_received():
    link, fake = _link()
    link.open()
    fake.feed(link_statistics_bytes(addr=0xEA))
    frames = link.poll_inbound()
    assert [f.type for f in frames] == [CrsfFrameType.LINK_STATISTICS]
    assert link.frames_received == 1
    # An empty read yields nothing and does not error.
    assert link.poll_inbound() == []


def test_crc_errors_are_counted():
    link, fake = _link()
    link.open()
    good = bytearray(link_statistics_bytes(addr=0xEA))
    good[-1] ^= 0xFF  # corrupt the CRC
    fake.feed(bytes(good) + link_statistics_bytes(addr=0xEA))
    frames = link.poll_inbound()
    # The corrupt frame is dropped-and-counted; the following good one survives.
    assert [f.type for f in frames] == [CrsfFrameType.LINK_STATISTICS]
    assert link.crc_errors == 1
