"""RC_CHANNELS_PACKED helpers: 11-bit channel packing + us<->tick mapping.

CRSF packs 16 channels of 11 bits each into a 22-byte payload, **LSB-first**
(little-endian bit order — distinct from the big-endian *telemetry* payloads).
The microsecond<->tick mapping endpoints are passed in (sourced from
``CrsfLinkSettings``) so nothing about the handset range is hardcoded here. Pure
functions, no I/O.
"""

from __future__ import annotations

from collections.abc import Sequence

#: An 11-bit channel value mask.
_CH_MASK = 0x7FF


def us_to_ticks(us: float, *, us_min: int, us_max: int, ticks_min: int, ticks_max: int) -> int:
    """Map a microsecond value to an 11-bit CRSF tick (clamped to 0..2047)."""
    span_us = us_max - us_min
    if span_us == 0:
        return ticks_min
    frac = (us - us_min) / span_us
    tick = round(ticks_min + frac * (ticks_max - ticks_min))
    return max(0, min(0x7FF, tick))


def ticks_to_us(tick: int, *, us_min: int, us_max: int, ticks_min: int, ticks_max: int) -> float:
    """Inverse of :func:`us_to_ticks` (for round-trip tests / display)."""
    span_ticks = ticks_max - ticks_min
    if span_ticks == 0:
        return float(us_min)
    frac = (tick - ticks_min) / span_ticks
    return us_min + frac * (us_max - us_min)


def pack_channels(ticks: Sequence[int], *, count: int, pad: int) -> bytes:
    """Pack ``ticks`` into an LSB-first 11-bit channel payload of ``count`` slots.

    ``count`` (RC channel count) and ``pad`` (the value used for unfilled slots,
    typically the mid-stick tick) are required keyword arguments sourced from
    ``CrsfLinkSettings`` by the caller, so no handset-specific magic number is
    baked into this helper. Shorter inputs are padded with ``pad``; longer inputs
    are truncated. Each value is masked to 11 bits.
    """
    values = list(ticks[:count]) + [pad] * max(0, count - len(ticks))
    acc = 0
    nbits = 0
    out = bytearray()
    for value in values:
        acc |= (value & _CH_MASK) << nbits
        nbits += 11
        while nbits >= 8:
            out.append(acc & 0xFF)
            acc >>= 8
            nbits -= 8
    if nbits > 0:
        out.append(acc & 0xFF)
    return bytes(out)


def unpack_channels(payload: bytes, *, count: int = 16) -> list[int]:
    """Unpack an LSB-first 11-bit channel payload into ``count`` tick values.

    Raises :class:`ValueError` (not a raw ``IndexError``) when ``payload`` is too
    short for ``count`` channels — e.g. a corrupted frame or a mismatched
    ``rc_channel_count``.
    """
    required = (count * 11 + 7) // 8
    if len(payload) < required:
        raise ValueError(
            f"payload too short for {count} channels: {len(payload)} < {required} bytes"
        )
    acc = 0
    nbits = 0
    channels: list[int] = []
    idx = 0
    while len(channels) < count:
        while nbits < 11:
            acc |= payload[idx] << nbits
            nbits += 8
            idx += 1
        channels.append(acc & _CH_MASK)
        acc >>= 11
        nbits -= 11
    return channels
