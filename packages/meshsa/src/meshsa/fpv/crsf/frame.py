"""CRSF frame model, CRC8 (DVB-S2), and stream framing.

Wire format (single frame)::

    [addr][len][type][payload ...][crc]
      0     1    2     3..N-1       N

* ``addr`` — device/sync byte (e.g. 0xC8 flight-controller, 0xEA handset).
* ``len``  — number of bytes *after* the length byte = ``len(payload) + 2``
  (the type byte plus the trailing CRC byte).
* ``crc``  — CRC8/DVB-S2 (poly 0xD5) computed over ``[type] + payload`` only —
  the addr and len bytes are excluded. Verified against the TBS CRSF spec,
  ExpressLRS ``crsf_protocol.h``, and Betaflight ``rx/crsf.c``.

These are protocol constants, not configuration: the CRC polynomial, the frame
type IDs, and the framing layout are fixed by the CRSF wire spec.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import IntEnum

from ..errors import CrcError

#: CRSF frames never exceed this many bytes on the wire (addr+len+payload+crc).
CRSF_MAX_FRAME_LEN = 64
#: Bytes of framing overhead outside the payload: addr + len + type + crc.
_OVERHEAD = 4
#: CRC8/DVB-S2 generator polynomial.
_CRC_POLY = 0xD5


class CrsfAddress(IntEnum):
    """CRSF device (sync) addresses — the first byte of every frame."""

    BROADCAST = 0x00
    FLIGHT_CONTROLLER = 0xC8
    RADIO_TRANSMITTER = 0xEA  # the handset (our default ``self`` address)
    CRSF_RECEIVER = 0xEC
    CRSF_TRANSMITTER = 0xEE


class CrsfFrameType(IntEnum):
    """CRSF frame type IDs (byte 2)."""

    GPS = 0x02
    BATTERY_SENSOR = 0x08
    LINK_STATISTICS = 0x14
    RC_CHANNELS_PACKED = 0x16
    ATTITUDE = 0x1E
    FLIGHT_MODE = 0x21
    DEVICE_PING = 0x28
    DEVICE_INFO = 0x29
    RADIO_ID = 0x3A


def _build_crc_table() -> tuple[int, ...]:
    """Precompute the 256-entry CRC8/DVB-S2 lookup table."""
    table = []
    for byte in range(256):
        crc = byte
        for _ in range(8):
            crc = ((crc << 1) ^ _CRC_POLY) & 0xFF if (crc & 0x80) else (crc << 1) & 0xFF
        table.append(crc)
    return tuple(table)


_CRC_TABLE = _build_crc_table()


def crc8_dvb_s2(data: bytes) -> int:
    """Return the CRC8/DVB-S2 checksum of ``data`` (poly 0xD5, init 0x00)."""
    crc = 0
    for byte in data:
        crc = _CRC_TABLE[crc ^ byte]
    return crc


@dataclass(frozen=True)
class CrsfFrame:
    """A parsed CRSF frame: device ``addr``, frame ``type``, raw ``payload``.

    ``type`` is kept as a plain ``int`` (not the enum) so unknown/vendor frame
    types round-trip without raising; use :attr:`type_name` for display.
    """

    addr: int
    type: int
    payload: bytes

    @property
    def type_name(self) -> str:
        """Human-readable type name, or hex for unknown types."""
        try:
            return CrsfFrameType(self.type).name
        except ValueError:
            return f"0x{self.type:02X}"

    def to_bytes(self) -> bytes:
        """Serialize to the on-wire byte sequence (with length + CRC)."""
        body = bytes([self.type]) + self.payload
        crc = crc8_dvb_s2(body)
        length = len(body) + 1  # body (type+payload) + crc byte
        return bytes([self.addr, length]) + body + bytes([crc])

    @classmethod
    def from_bytes(cls, data: bytes) -> CrsfFrame:
        """Parse and CRC-verify exactly one complete frame from ``data``.

        ``data`` must be a single complete frame (addr..crc inclusive). Raises
        :class:`ValueError` on a malformed length and :class:`CrcError` on a CRC
        mismatch.
        """
        if len(data) < _OVERHEAD:
            raise ValueError(f"frame too short: {len(data)} bytes")
        length = data[1]
        total = length + 2  # addr + len + (length bytes)
        if total != len(data):
            raise ValueError(f"length byte {length} != frame size {len(data) - 2}")
        ftype = data[2]
        payload = data[3:-1]
        expected = data[-1]
        actual = crc8_dvb_s2(data[2:-1])  # CRC covers type + payload only
        if actual != expected:
            raise CrcError(f"crc mismatch: got 0x{actual:02X}, want 0x{expected:02X}")
        return cls(addr=data[0], type=ftype, payload=payload)


#: Device addresses a frame may legitimately start with. Resync gates on this so
#: a misaligned window inside corrupt data cannot masquerade as a frame start
#: (an all-zero or random window has only a 1/256 chance of a valid CRC, and the
#: address gate removes essentially all of those false positives). BROADCAST
#: (0x00) is excluded: a zero byte is far too common inside payloads to be a
#: reliable frame delimiter, and the module never originates broadcast frames on
#: the handset line.
_SYNC_ADDRESSES: frozenset[int] = frozenset(
    int(a) for a in CrsfAddress if a is not CrsfAddress.BROADCAST
)


def extract_frames(
    buffer: bytearray,
    *,
    max_frame_len: int = CRSF_MAX_FRAME_LEN,
    sync_addresses: frozenset[int] = _SYNC_ADDRESSES,
    on_crc_error: Callable[[], None] | None = None,
) -> list[CrsfFrame]:
    """Drain all complete, CRC-valid frames from ``buffer`` in place.

    Consumes parsed bytes from the front of ``buffer`` and leaves any trailing
    partial frame for the next call. Resynchronisation is **address-gated**: a
    frame may only start on a byte in ``sync_addresses`` (CRSF frames always lead
    with a device address), so a CRC-bad or truncated frame is skipped by
    advancing to the next plausible address rather than blindly byte-walking into
    the following good frame. ``on_crc_error`` (if given) is called once per
    CRC-failed candidate so the link layer can maintain a ``crc_errors`` counter.
    Pure with respect to the bytes (no I/O).
    """
    frames: list[CrsfFrame] = []
    while len(buffer) >= _OVERHEAD:
        # Resync: drop bytes until the head is a plausible frame start.
        if buffer[0] not in sync_addresses:
            del buffer[0]
            continue
        length = buffer[1]
        total = length + 2
        if length < 2 or total > max_frame_len:
            del buffer[0]  # implausible length: skip this address, keep scanning
            continue
        if len(buffer) < total:
            break  # incomplete trailing frame; wait for more bytes
        candidate = bytes(buffer[:total])
        try:
            frames.append(CrsfFrame.from_bytes(candidate))
        except CrcError:
            if on_crc_error is not None:
                on_crc_error()
            del buffer[0]  # bad frame: resync from the next byte
            continue
        except ValueError:  # pragma: no cover - candidate length is validated above
            del buffer[0]
            continue
        del buffer[:total]
    return frames
