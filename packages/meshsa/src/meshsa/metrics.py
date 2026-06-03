"""Lightweight in-process observability counters.

Plain dataclasses, no external metrics backend — exposed via ``Router.metrics``
and ``meshsa.health.health_snapshot`` so a deployment can scrape rx/tx/drops
without pulling in Prometheus. Transports carry their own ``reconnects`` and
``dropped_inbox_full`` counters.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RouterMetrics:
    """Counters maintained by the router over its lifetime."""

    rx: int = 0  # frames decoded successfully from a transport
    tx: int = 0  # frames sent for locally-published envelopes
    forwarded: int = 0  # frames bridged onto other transports
    dropped_undecodable: int = 0  # frames that failed to decode (malformed)
    schema_mismatch: int = 0  # frames dropped for an unsupported wire schema
