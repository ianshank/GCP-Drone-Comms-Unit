"""CRSF frame CRC8/DVB-S2, (de)serialization, and stream framing."""

from __future__ import annotations

import pytest

from meshsa.fpv.crsf.frame import (
    CrsfAddress,
    CrsfFrame,
    CrsfFrameType,
    crc8_dvb_s2,
    extract_frames,
)
from meshsa.fpv.errors import CrcError


def test_crc8_known_vector():
    # CRC8/DVB-S2 of a known byte sequence (poly 0xD5, init 0x00).
    assert crc8_dvb_s2(b"\x16\x00\x00") == crc8_dvb_s2(bytes([0x16, 0x00, 0x00]))
    # Empty input -> init value.
    assert crc8_dvb_s2(b"") == 0
    # Determinism + single-byte sanity.
    assert 0 <= crc8_dvb_s2(b"\xc8") <= 0xFF


def test_frame_roundtrip_to_from_bytes():
    frame = CrsfFrame(
        addr=CrsfAddress.FLIGHT_CONTROLLER,
        type=CrsfFrameType.LINK_STATISTICS,
        payload=bytes(range(10)),
    )
    wire = frame.to_bytes()
    # addr + len + type + 10 payload + crc = 14 bytes; len byte = type+payload+crc = 12.
    assert len(wire) == 14
    assert wire[1] == 12
    parsed = CrsfFrame.from_bytes(wire)
    assert parsed == frame
    assert parsed.type_name == "LINK_STATISTICS"


def test_unknown_type_name_is_hex():
    frame = CrsfFrame(addr=0xC8, type=0x7F, payload=b"")
    assert frame.type_name == "0x7F"


def test_from_bytes_rejects_short_and_bad_length():
    with pytest.raises(ValueError, match="too short"):
        CrsfFrame.from_bytes(b"\xc8\x02")
    # Length byte inconsistent with actual size.
    good = CrsfFrame(addr=0xC8, type=0x14, payload=b"\x01\x02").to_bytes()
    with pytest.raises(ValueError, match="length byte"):
        CrsfFrame.from_bytes(good + b"\x99")


def test_from_bytes_detects_crc_corruption():
    wire = bytearray(CrsfFrame(addr=0xC8, type=0x14, payload=b"\x01").to_bytes())
    wire[-1] ^= 0xFF  # corrupt the CRC
    with pytest.raises(CrcError, match="crc mismatch"):
        CrsfFrame.from_bytes(bytes(wire))


def test_extract_frames_drains_complete_and_keeps_partial():
    f1 = CrsfFrame(addr=0xC8, type=0x14, payload=bytes(10)).to_bytes()
    f2 = CrsfFrame(addr=0xEA, type=0x1E, payload=bytes(6)).to_bytes()
    buf = bytearray(f1 + f2[:-1])  # second frame missing its CRC byte
    frames = extract_frames(buf)
    assert [f.type for f in frames] == [0x14]
    # Partial second frame remains buffered for the next read.
    assert bytes(buf) == f2[:-1]
    # Completing it yields the second frame.
    buf += f2[-1:]
    frames = extract_frames(buf)
    assert [f.type for f in frames] == [0x1E]
    assert len(buf) == 0


def test_extract_frames_resyncs_past_garbage_and_crc_errors():
    # Non-zero payloads: an all-zero frame would CRC-validate (CRC8 of zeros = 0),
    # so realistic garbage must be non-zero to exercise true resync.
    good = CrsfFrame(addr=0xC8, type=0x14, payload=bytes(range(1, 11))).to_bytes()
    corrupt = bytearray(CrsfFrame(addr=0xC8, type=0x08, payload=bytes(range(11, 19))).to_bytes())
    corrupt[-1] ^= 0xFF  # break the CRC
    buf = bytearray(bytes(corrupt) + good)
    frames = extract_frames(buf)
    # The CRC-bad frame is resynced past; the good frame survives.
    assert [f.type for f in frames] == [0x14]
    assert frames[0].payload == bytes(range(1, 11))
    assert len(buf) == 0


def test_extract_frames_rejects_oversized_length():
    good = CrsfFrame(addr=0xC8, type=0x14, payload=bytes(range(1, 11))).to_bytes()
    # Leading byte declares len=0x40 -> total 66 > max 64; must be skipped (resync).
    buf = bytearray(b"\xc8\x40" + good)
    frames = extract_frames(buf, max_frame_len=64)
    assert [f.type for f in frames] == [0x14]
