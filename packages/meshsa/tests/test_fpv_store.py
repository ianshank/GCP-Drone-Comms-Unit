"""TelemetryStore: latest-value semantics and type isolation (§5.2).

The ``age_s``/``history`` accessors and their ring were removed in T-5.1a
(no production readers); the constructor still validates ``history_len`` for
compatibility with the monitor/replay tools that thread it.
"""

from __future__ import annotations

import pytest

from meshsa.fpv.crsf.telemetry import Attitude, BatterySensor, LinkStatistics
from meshsa.fpv.telemetry_store import TelemetryStore


def _ls(lq: int) -> LinkStatistics:
    return LinkStatistics(-60, -60, lq, 8, 0, 0, 100, -60, 100, 8)


def test_rejects_nonpositive_history_len():
    with pytest.raises(ValueError, match="history_len"):
        TelemetryStore(history_len=0)


def test_latest_returns_newest_with_timestamp():
    store = TelemetryStore()
    assert store.latest(LinkStatistics) is None
    store.update(_ls(99), t_mono=5.0)
    msg, t = store.latest(LinkStatistics)
    assert msg.uplink_lq == 99
    assert t == 5.0
    store.update(_ls(42), t_mono=6.0)
    assert store.latest(LinkStatistics)[0].uplink_lq == 42


def test_type_isolation():
    store = TelemetryStore()
    store.update(_ls(80), t_mono=1.0)
    store.update(BatterySensor(16.8, 5.0, 100, 90), t_mono=2.0)
    assert store.latest(LinkStatistics)[0].uplink_lq == 80
    assert store.latest(BatterySensor)[0].remaining_pct == 90
    # Unrelated type unaffected.
    assert store.latest(Attitude) is None
