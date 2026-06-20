"""CRSF wire layer: frame model + CRC, pure telemetry parsers, the serial link.

Protocol constants (sync/address bytes, CRC polynomial, frame type IDs, the
11-bit RC channel width) are fixed by the CRSF specification and live in
:mod:`meshsa.fpv.crsf.frame`; they are not deployment tunables.
"""

from __future__ import annotations

from .frame import (
    CrsfAddress,
    CrsfFrame,
    CrsfFrameType,
    crc8_dvb_s2,
    extract_frames,
)

__all__ = [
    "CrsfAddress",
    "CrsfFrame",
    "CrsfFrameType",
    "crc8_dvb_s2",
    "extract_frames",
]
