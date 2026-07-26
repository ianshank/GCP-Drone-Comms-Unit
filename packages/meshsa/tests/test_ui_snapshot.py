"""Tests for meshsa.ui.snapshot — upsert/eviction/TTL/forward-compat (spec §5.2, §7)."""

from __future__ import annotations

from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from meshsa.models import Envelope, MessageKind
from meshsa.ui.snapshot import SnapshotStore


class FakeClock:
    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def now(self) -> float:
        return self.t


def _store(
    clock: FakeClock,
    *,
    max_tracks: int = 8,
    max_detections: int = 8,
    track_stale_s: float = 100.0,
    detection_stale_s: float = 100.0,
) -> SnapshotStore:
    return SnapshotStore(
        clock,
        max_tracks=max_tracks,
        max_detections=max_detections,
        track_stale_s=track_stale_s,
        detection_stale_s=detection_stale_s,
    )


def _pli(uid: str, *, msg_id: str = "m", ts: float = 1.0, **position: Any) -> Envelope:
    pos = {"lat": 38.5, "lon": -122.5, **position}
    return Envelope(
        msg_id=f"{msg_id}-{uid}-{ts}",
        ts=ts,
        source_uid=uid,
        kind=MessageKind.PLI,
        payload={"node": {"uid": uid, "callsign": uid.upper()}, "position": pos},
    )


def _marker(
    uid: str,
    *,
    msg_id: str,
    track_id: int | None = None,
    ts: float = 1.0,
    label: str = "person",
) -> Envelope:
    detection: dict[str, Any] = {"label": label, "confidence": 0.9}
    if track_id is not None:
        detection["track_id"] = track_id
    return Envelope(
        msg_id=msg_id,
        ts=ts,
        source_uid=uid,
        kind=MessageKind.MARKER,
        payload={
            "node": {"uid": uid, "callsign": uid.upper()},
            "position": {"lat": 10.0, "lon": 20.0},
            "detection": detection,
        },
    )


# ── construction guards ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_tracks": 0},
        {"max_detections": 0},
        {"track_stale_s": 0.0},
        {"detection_stale_s": -1.0},
    ],
)
def test_invalid_bounds_rejected(kwargs: dict[str, Any]) -> None:
    defaults: dict[str, Any] = {
        "max_tracks": 1,
        "max_detections": 1,
        "track_stale_s": 1.0,
        "detection_stale_s": 1.0,
    }
    defaults.update(kwargs)
    with pytest.raises(ValueError):
        SnapshotStore(FakeClock(), **defaults)


# ── upsert semantics ──────────────────────────────────────────────────────────


def test_pli_upserts_by_source_uid() -> None:
    store = _store(FakeClock())
    store.handle(_pli("a", ts=1.0))
    store.handle(_pli("a", ts=2.0))
    fc = store.tracks_geojson()
    assert len(fc["features"]) == 1
    assert fc["features"][0]["properties"]["ts"] == 2.0


def test_marker_composite_key_distinguishes_sources() -> None:
    # track_id is per-source tracker numbering: two nodes both emitting track_id=1
    # must stay two detections (design D-1).
    store = _store(FakeClock())
    store.handle(_marker("a", msg_id="m1", track_id=1))
    store.handle(_marker("b", msg_id="m2", track_id=1))
    assert len(store.detections_geojson()["features"]) == 2


def test_marker_same_source_same_track_upserts() -> None:
    store = _store(FakeClock())
    store.handle(_marker("a", msg_id="m1", track_id=1, ts=1.0))
    store.handle(_marker("a", msg_id="m2", track_id=1, ts=2.0))
    features = store.detections_geojson()["features"]
    assert len(features) == 1
    assert features[0]["properties"]["ts"] == 2.0


def test_marker_without_track_id_falls_back_to_msg_id() -> None:
    store = _store(FakeClock())
    store.handle(_marker("a", msg_id="m1"))
    store.handle(_marker("a", msg_id="m2"))
    assert len(store.detections_geojson()["features"]) == 2


def test_chat_and_status_ignored() -> None:
    store = _store(FakeClock())
    store.handle(
        Envelope(msg_id="c1", ts=1.0, source_uid="a", kind=MessageKind.CHAT, payload={"text": "x"})
    )
    store.handle(Envelope(msg_id="s1", ts=1.0, source_uid="a", kind=MessageKind.STATUS, payload={}))
    assert store.tracks_geojson()["features"] == []
    assert store.detections_geojson()["features"] == []
    assert store.counters()["dropped_invalid"] == 0


# ── invalid payloads fail loudly-but-safely ───────────────────────────────────


@pytest.mark.parametrize(
    "payload",
    [
        {},  # no position block
        {"position": "not-a-dict"},
        {"position": {"lat": "x", "lon": 0.0}},
        {"position": {"lon": 0.0}},  # missing lat
    ],
)
def test_unusable_position_dropped_and_counted(payload: dict[str, Any]) -> None:
    store = _store(FakeClock())
    store.handle(
        Envelope(msg_id="m1", ts=1.0, source_uid="a", kind=MessageKind.PLI, payload=payload)
    )
    assert store.tracks_geojson()["features"] == []
    assert store.counters()["dropped_invalid"] == 1


# ── eviction: caps + TTL ──────────────────────────────────────────────────────


def test_cap_evicts_oldest_first() -> None:
    clock = FakeClock()
    store = _store(clock, max_tracks=2)
    for i, uid in enumerate(["a", "b", "c"]):
        clock.t = float(i)
        store.handle(_pli(uid))
    uids = [f["properties"]["uid"] for f in store.tracks_geojson()["features"]]
    assert uids == ["b", "c"]
    assert store.counters()["tracks_evicted"] == 1


def test_upsert_refreshes_recency_for_eviction_order() -> None:
    clock = FakeClock()
    store = _store(clock, max_tracks=2)
    store.handle(_pli("a"))
    store.handle(_pli("b"))
    store.handle(_pli("a"))  # refresh: b is now oldest
    store.handle(_pli("c"))
    uids = {f["properties"]["uid"] for f in store.tracks_geojson()["features"]}
    assert uids == {"a", "c"}


def test_ttl_sweep_on_read() -> None:
    clock = FakeClock()
    store = _store(clock, track_stale_s=10.0, detection_stale_s=50.0)
    store.handle(_pli("a"))
    store.handle(_marker("a", msg_id="m1", track_id=1))
    clock.t = 11.0
    assert store.tracks_geojson()["features"] == []  # track TTL passed
    assert len(store.detections_geojson()["features"]) == 1  # detection TTL not yet
    clock.t = 51.0
    assert store.detections_geojson()["features"] == []
    counters = store.counters()
    assert counters["tracks_expired"] == 1
    assert counters["detections_expired"] == 1
    assert counters["tracks_live"] == 0
    assert counters["detections_live"] == 0


# ── forward compatibility (spec §6) ───────────────────────────────────────────


def test_unknown_scalar_keys_pass_through() -> None:
    store = _store(FakeClock())
    env = _pli("a", course_deg=45.0, speed_ms=3.0)
    env.payload["rssi_dbm"] = -71  # unknown top-level scalar (M3 additive pattern)
    env.payload["position"]["fix_quality"] = "rtk"  # unknown scalar inside a known block
    store.handle(env)
    props = store.tracks_geojson()["features"][0]["properties"]
    assert props["course_deg"] == 45.0
    assert props["speed_ms"] == 3.0
    assert props["rssi_dbm"] == -71
    assert props["fix_quality"] == "rtk"


def test_nonscalar_unknowns_ignored_and_counted() -> None:
    store = _store(FakeClock())
    env = _pli("a")
    env.payload["waypoints"] = [{"lat": 1.0}]  # non-scalar unknown: never rendered
    env.payload["position"]["cov"] = [[1.0]]
    store.handle(env)
    props = store.tracks_geojson()["features"][0]["properties"]
    assert "waypoints" not in props
    assert "cov" not in props
    assert store.counters()["ignored_nonscalar_keys"] == 2


def test_nonscalar_callsign_omitted() -> None:
    store = _store(FakeClock())
    env = _pli("a")
    env.payload["node"] = {"uid": "a", "callsign": {"nested": True}}
    store.handle(env)
    assert "callsign" not in store.tracks_geojson()["features"][0]["properties"]


def test_telemetry_scalars_prefixed() -> None:
    store = _store(FakeClock())
    env = _pli("a")
    env.payload["telemetry"] = {"battery_pct": 80, "attitude": {"yaw_deg": 1.0}}
    store.handle(env)
    props = store.tracks_geojson()["features"][0]["properties"]
    assert props["telemetry_battery_pct"] == 80
    assert "telemetry_attitude" not in props  # nested block: ignored, counted


# ── golden vector (spec §7) ───────────────────────────────────────────────────


def test_golden_feature_collection() -> None:
    store = _store(FakeClock(t=5.0))
    pli = _pli("drone-1", ts=4.0, hae=120.0, course_deg=90.0)
    store.handle(pli)
    store.handle(_marker("scout-2", msg_id="det-7", track_id=3, ts=4.5, label="vehicle"))
    assert store.tracks_geojson() == {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [-122.5, 38.5]},
                "properties": {
                    "uid": "drone-1",
                    "ts": 4.0,
                    "kind": "pli",
                    "callsign": "DRONE-1",
                    "hae": 120.0,
                    "course_deg": 90.0,
                },
            }
        ],
    }
    assert store.detections_geojson() == {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [20.0, 10.0]},
                "properties": {
                    "uid": "scout-2",
                    "ts": 4.5,
                    "kind": "marker",
                    "callsign": "SCOUT-2",
                    "label": "vehicle",
                    "confidence": 0.9,
                    "track_id": 3,
                },
            }
        ],
    }
    # Negative: a wrong decode (position missing) must not appear as a feature.
    store.handle(
        Envelope(msg_id="bad", ts=5.0, source_uid="x", kind=MessageKind.MARKER, payload={})
    )
    assert len(store.detections_geojson()["features"]) == 1


# ── property-based invariants (Hypothesis; spec §7) ───────────────────────────


_uids = st.sampled_from(["a", "b", "c", "d", "e"])
_track_ids = st.one_of(st.none(), st.integers(min_value=0, max_value=3))


@st.composite
def _events(draw: st.DrawFn) -> tuple[str, str, int | None, float]:
    kind = draw(st.sampled_from(["pli", "marker"]))
    uid = draw(_uids)
    track_id = draw(_track_ids) if kind == "marker" else None
    dt = draw(st.floats(min_value=0.0, max_value=20.0, allow_nan=False))
    return kind, uid, track_id, dt


@settings(max_examples=60, deadline=None)
@given(st.lists(_events(), max_size=60))
def test_store_never_exceeds_caps_or_serves_stale(
    events: list[tuple[str, str, int | None, float]],
) -> None:
    clock = FakeClock()
    cap_t, cap_d, ttl = 3, 4, 15.0
    store = _store(
        clock, max_tracks=cap_t, max_detections=cap_d, track_stale_s=ttl, detection_stale_s=ttl
    )
    seen_at: dict[tuple[str, str], float] = {}
    for i, (kind, uid, track_id, dt) in enumerate(events):
        clock.t += dt
        if kind == "pli":
            store.handle(_pli(uid, ts=clock.t, msg_id=f"p{i}"))
            seen_at[("t", uid)] = clock.t
        else:
            store.handle(_marker(uid, msg_id=f"m{i}", track_id=track_id, ts=clock.t))
        tracks = store.tracks_geojson()["features"]
        dets = store.detections_geojson()["features"]
        assert len(tracks) <= cap_t
        assert len(dets) <= cap_d
        # No served track is older than its TTL (its properties carry the last-envelope ts,
        # which equals its ingest time in this model).
        for feature in tracks:
            assert clock.t - feature["properties"]["ts"] <= ttl
        # Upsert idempotence per key: no duplicate uids among tracks.
        uids = [f["properties"]["uid"] for f in tracks]
        assert len(uids) == len(set(uids))


# ── review regressions: non-finite floats + counters sweep ────────────────────


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_coordinates_dropped_and_counted(bad: float) -> None:
    store = _store(FakeClock())
    store.handle(_pli("a", lat=bad))
    store.handle(_pli("b", lon=bad))
    assert store.tracks_geojson()["features"] == []
    assert store.counters()["dropped_invalid"] == 2


def test_nonfinite_scalar_property_excluded() -> None:
    store = _store(FakeClock())
    store.handle(_pli("a", speed=float("nan")))
    (feature,) = store.tracks_geojson()["features"]
    # NaN/inf are not valid JSON: excluded from properties, counted like non-scalars.
    assert "speed" not in feature["properties"]
    assert store.counters()["ignored_nonscalar_keys"] == 1


def test_counters_sweeps_expired_before_reporting_live() -> None:
    clock = FakeClock()
    store = _store(clock, track_stale_s=10.0, detection_stale_s=10.0)
    store.handle(_pli("a"))
    store.handle(_marker("a", msg_id="d1", track_id=1))
    clock.t = 50.0  # both entries are now past their TTL
    counters = store.counters()  # health-only poll: no GeoJSON read first
    assert counters["tracks_live"] == 0
    assert counters["detections_live"] == 0
    assert counters["tracks_expired"] == 1
    assert counters["detections_expired"] == 1
