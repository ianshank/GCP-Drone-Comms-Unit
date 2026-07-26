"""Tests for meshsa.ui.logring — capacity, level floor, scalar-only entries (spec §5.4)."""

from __future__ import annotations

from typing import Any

import pytest
import structlog

from meshsa.ui.logring import LogRing


class FakeClock:
    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def now(self) -> float:
        return self.t


def _emit(ring: LogRing, method: str, event: str, **kv: Any) -> dict[str, Any]:
    return ring.processor(None, method, {"event": event, **kv})


def test_construction_guards() -> None:
    with pytest.raises(ValueError):
        LogRing(0)
    with pytest.raises(ValueError):
        LogRing(10, level="loud")


def test_capacity_bounded_newest_kept() -> None:
    ring = LogRing(3, clock=FakeClock())
    for i in range(5):
        _emit(ring, "info", f"e{i}")
    events = [e["event"] for e in ring.entries()]
    assert events == ["e2", "e3", "e4"]


def test_level_floor() -> None:
    ring = LogRing(10, level="warning", clock=FakeClock())
    _emit(ring, "debug", "quiet")
    _emit(ring, "info", "still-quiet")
    _emit(ring, "warning", "kept")
    _emit(ring, "error", "kept-too")
    _emit(ring, "made_up_level", "unknown-methods-are-not-silently-dropped")
    events = [e["event"] for e in ring.entries()]
    assert "quiet" not in events and "still-quiet" not in events
    assert events[:2] == ["kept", "kept-too"]
    # Unknown method names are treated at the default level (info) — below a warning
    # floor they are excluded, but never crash the pipeline.
    assert "unknown-methods-are-not-silently-dropped" not in events


def test_scalar_only_entries() -> None:
    ring = LogRing(10, clock=FakeClock(t=7.0))
    _emit(ring, "info", "evt", count=3, ok=True, name="x", ratio=0.5, none=None, blob={"a": 1})
    (entry,) = ring.entries()
    assert entry["event"] == "evt"
    assert entry["count"] == 3 and entry["ok"] is True and entry["name"] == "x"
    assert entry["ratio"] == 0.5 and entry["none"] is None
    assert "blob" not in entry  # non-scalar bound values never enter the ring
    assert entry["ts"] == 7.0  # clock fallback when no scalar timestamp is bound
    assert entry["level"] == "info"


def test_timestamp_from_event_dict_wins() -> None:
    ring = LogRing(10, clock=FakeClock(t=7.0))
    ring.processor(None, "info", {"event": "evt", "timestamp": 3.5})
    assert ring.entries()[0]["ts"] == 3.5


def test_processor_returns_event_dict_unchanged() -> None:
    ring = LogRing(10, clock=FakeClock())
    event_dict = {"event": "evt", "blob": {"a": 1}, "n": 1}
    out = ring.processor(None, "info", event_dict)
    assert out is event_dict
    assert out == {"event": "evt", "blob": {"a": 1}, "n": 1}


def test_entries_returns_copies() -> None:
    ring = LogRing(10, clock=FakeClock())
    _emit(ring, "info", "evt")
    ring.entries()[0]["event"] = "mutated"
    assert ring.entries()[0]["event"] == "evt"


def test_install_prepends_once_and_output_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    original = structlog.get_config().get("processors", [])
    try:
        ring = LogRing(10, clock=FakeClock())
        ring.install()
        ring.install()  # idempotent: not added twice
        processors = structlog.get_config()["processors"]
        assert processors.count(ring.processor) == 1
        assert processors[0] == ring.processor
        logger = structlog.get_logger("meshsa.ui.test")
        logger.info("ring_probe", value=1)
        assert any(e["event"] == "ring_probe" and e.get("value") == 1 for e in ring.entries())
    finally:
        structlog.configure(processors=original)
