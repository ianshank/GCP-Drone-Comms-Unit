"""Lightweight in-process observability counters.

Plain dataclasses, no external metrics backend — exposed via ``Router.metrics``
and ``meshsa.health.health_snapshot`` so a deployment can scrape rx/tx/drops
without pulling in Prometheus. Transports carry their own ``reconnects`` and
``dropped_inbox_full`` counters.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass


@dataclass
class RouterMetrics:
    """Counters maintained by the router over its lifetime."""

    rx: int = 0  # frames decoded successfully from a transport
    tx: int = 0  # frames sent for locally-published envelopes
    forwarded: int = 0  # frames bridged onto other transports
    dropped_undecodable: int = 0  # frames that failed to decode (malformed)
    schema_mismatch: int = 0  # frames dropped for an unsupported wire schema

    def as_dict(self) -> dict[str, int]:
        """Return the counters as a plain ``{name: value}`` dict."""
        return asdict(self)


#: Per-transport counter keys surfaced as Prometheus gauges (snapshot key ->
#: exported metric name); a transport may omit any of these (default ``0``).
_TRANSPORT_METRICS = {
    "dropped_inbox_full": "meshsa_transport_dropped_inbox_full",
    "reconnects": "meshsa_transport_reconnects",
    "rx_frames": "meshsa_transport_rx_frames",
}


def render_prometheus(metrics: RouterMetrics, transports: Mapping[str, Mapping[str, int]]) -> str:
    """Render router + per-transport counters as Prometheus text-exposition lines.

    Hand-rolled text (no ``prometheus_client`` dependency): one ``name value``
    line per router counter, plus one ``name{transport="..."} value`` line per
    per-transport counter for each transport. Missing per-transport keys default
    to ``0`` so the exported series set is stable across transport types.
    """
    lines = [
        f"meshsa_rx_total {metrics.rx}",
        f"meshsa_tx_total {metrics.tx}",
        f"meshsa_forwarded_total {metrics.forwarded}",
        f"meshsa_dropped_undecodable_total {metrics.dropped_undecodable}",
        f"meshsa_schema_mismatch_total {metrics.schema_mismatch}",
    ]
    for name, counters in transports.items():
        for key, metric in _TRANSPORT_METRICS.items():
            value = counters.get(key, 0)
            lines.append(f'{metric}{{transport="{name}"}} {value}')
    return "\n".join(lines) + "\n"
