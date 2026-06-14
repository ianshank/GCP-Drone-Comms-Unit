"""TelemetryStore: latest/age/history, ring bound, type isolation (§5.2)."""

from __future__ import annotations

import pytest

from meshsa.fpv.crsf.telemetry import Attitude, BatterySensor, LinkStatistics
from meshsa.fpv.telemetry_store import TelemetryStore


def _ls(lq: int) -> LinkStatistics:
    return LinkStatistics(-60, -60, lq, 8, 0, 0, 100, -60, 100, 8)


def test_rejects_nonpositive_history_len():
    with pytest.raises(ValueError, match="history_len"):
        TelemetryStore(history_len=0)


def test_latest_and_age():
    store = TelemetryStore()
    assert store.latest(LinkStatistics) is None
    assert store.age_s(LinkStatistics, now=10.0) is None
    store.update(_ls(99), t_mono=5.0)
    msg, t = store.latest(LinkStatistics)
    assert msg.uplink_lq == 99
    assert t == 5.0
    assert store.age_s(LinkStatistics, now=7.5) == pytest.approx(2.5)


def test_history_is_bounded_and_ordered():
    store = TelemetryStore(history_len=3)
    for i in range(5):
        store.update(_ls(i), t_mono=float(i))
    hist = store.history(LinkStatistics, n=10)
    # Ring keeps only the last 3, oldest-first.
    assert [m.uplink_lq for m, _ in hist] == [2, 3, 4]
    # Requesting fewer returns the most recent slice.
    assert [m.uplink_lq for m, _ in store.history(LinkStatistics, n=2)] == [3, 4]
    assert store.history(LinkStatistics, n=0) == []


def test_history_empty_for_unseen_type():
    store = TelemetryStore()
    assert store.history(Attitude, n=5) == []


def test_type_isolation():
    store = TelemetryStore()
    store.update(_ls(80), t_mono=1.0)
    store.update(BatterySensor(16.8, 5.0, 100, 90), t_mono=2.0)
    assert store.latest(LinkStatistics)[0].uplink_lq == 80
    assert store.latest(BatterySensor)[0].remaining_pct == 90
    # Unrelated type unaffected.
    assert store.latest(Attitude) is None
