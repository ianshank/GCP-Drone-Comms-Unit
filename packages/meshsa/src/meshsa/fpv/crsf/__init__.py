"""CRSF wire layer: frame model + CRC, pure telemetry parsers, the serial link.

Protocol constants (sync/address bytes, CRC polynomial, frame type IDs, the
11-bit RC channel width) are fixed by the CRSF specification and live in
:mod:`meshsa.fpv.crsf.frame`; they are not deployment tunables.

No re-exports (T-5.1a): every consumer imports from the concrete submodule
(``.frame``, ``.link``, ``.telemetry``, ``.rc``) — the previous package-level
aliases had no importers.
"""

from __future__ import annotations
