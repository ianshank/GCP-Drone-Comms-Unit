"""RC channel packing + microsecond<->tick mapping (meshsa.fpv.crsf.rc)."""

from __future__ import annotations

import pytest

from meshsa.fpv.crsf.rc import pack_channels, ticks_to_us, unpack_channels, us_to_ticks

_MAP = dict(us_min=988, us_max=2012, ticks_min=172, ticks_max=1811)


def test_us_to_ticks_endpoints_and_clamp():
    assert us_to_ticks(988, **_MAP) == 172
    assert us_to_ticks(2012, **_MAP) == 1811
    # Out-of-range values clamp to the 11-bit domain.
    assert us_to_ticks(500, **_MAP) >= 0
    assert us_to_ticks(5000, **_MAP) == 0x7FF


def test_ticks_to_us_is_inverse():
    for us in (1000, 1500, 2000):
        tick = us_to_ticks(us, **_MAP)
        assert ticks_to_us(tick, **_MAP) == pytest.approx(us, abs=1.0)


def test_us_to_ticks_zero_span_returns_ticks_min():
    # A degenerate handset range (us_min == us_max) must not divide by zero; it
    # returns ticks_min. Pure-logic guard (previously pragma-excluded).
    assert us_to_ticks(1500, us_min=1000, us_max=1000, ticks_min=172, ticks_max=1811) == 172


def test_ticks_to_us_zero_span_returns_us_min():
    # Inverse degenerate case (ticks_min == ticks_max) returns float(us_min).
    assert ticks_to_us(900, us_min=988, us_max=2012, ticks_min=500, ticks_max=500) == 988.0


def test_pack_unpack_roundtrip_16_channels():
    ticks = [172, 992, 1811, 500, 1000, 1500, 0, 2047, 100, 200, 300, 400, 500, 600, 700, 800]
    payload = pack_channels(ticks, count=16, pad=992)
    assert len(payload) == 22  # 16 * 11 bits = 176 bits = 22 bytes
    assert unpack_channels(payload, count=16) == ticks


def test_pack_pads_short_and_truncates_long():
    padded = pack_channels([172, 1811], count=16, pad=992)
    chans = unpack_channels(padded, count=16)
    assert chans[0] == 172
    assert chans[1] == 1811
    assert chans[2:] == [992] * 14  # padded with the center value
    # Too many channels: extra ones are dropped.
    long = pack_channels(list(range(20)), count=16, pad=992)
    assert len(unpack_channels(long, count=16)) == 16


def test_unpack_short_payload_raises_valueerror():
    # A truncated payload must fail with a clear ValueError, not an IndexError.
    with pytest.raises(ValueError, match="payload too short"):
        unpack_channels(b"\x00\x00", count=16)  # 16 channels need 22 bytes


def test_pack_unpack_non_byte_aligned_count():
    # count=1 -> 11 bits -> 2 bytes (flushes the trailing partial byte).
    payload = pack_channels([1337], count=1, pad=992)
    assert len(payload) == 2
    assert unpack_channels(payload, count=1) == [1337]
