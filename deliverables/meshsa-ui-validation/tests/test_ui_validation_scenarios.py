"""Named validation scenarios S1–S6 for ``meshsa.ui`` (plan Gate 1).

These tests are additive to the existing ``test_ui_app.py`` / ``test_ui_snapshot.py``
suite.  Every scenario is:

* **fakes-only** — no hardware, no radios, no live sockets beyond aiohttp's
  in-process ``TestServer``.
* **named explicitly** — the function name IS the scenario identifier so CI
  output and coverage maps are traceable to the plan.
* **non-overlapping** with the existing suite — the existing tests cover happy-
  path upserts, construction guards, and generic auth; these cover the four
  field-validation scenarios plus the two security gaps identified in the peer
  review.

Drop this file into ``packages/meshsa/tests/`` and run the full suite:

    cd packages/meshsa && pytest tests/test_ui_validation_scenarios.py -v

All six scenarios are expected to pass green against the current codebase.
Scenario S4 includes one ``xfail`` marker for the currently-unimplemented
``X-Snapshot-Age`` response header — the xfail documents the gap and will flip
to xpass automatically once the header is added to ``build_ui_app``.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from meshsa.models import Envelope, MessageKind
from meshsa.ui.app import build_ui_app
from meshsa.ui.config import UIConfig
from meshsa.ui.snapshot import SnapshotStore
from meshsa.ui.sources import UISources

# ---------------------------------------------------------------------------
# Shared fakes — local to this module; do not import from test_ui_app to keep
# the scenarios self-contained and independently runnable.
# ---------------------------------------------------------------------------


class FakeClock:
    """Injectable monotonic clock whose current time is mutable in tests."""

    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def now(self) -> float:
        return self.t


class FakeHealth:
    def snapshot(self) -> dict[str, Any]:
        return {"health": {"status": "ok"}, "metrics": {}}


class _FakeSnapshot:
    """Minimal SnapshotSource wrapping a real SnapshotStore for HTTP-layer tests."""

    def __init__(self, store: SnapshotStore) -> None:
        self._store = store

    def tracks_geojson(self) -> dict[str, Any]:
        return self._store.tracks_geojson()

    def detections_geojson(self) -> dict[str, Any]:
        return self._store.detections_geojson()

    def counters(self) -> dict[str, int]:
        return self._store.counters()


def _make_store(
    clock: FakeClock,
    *,
    max_tracks: int = 64,
    max_detections: int = 64,
    track_stale_s: float = 300.0,
    detection_stale_s: float = 3600.0,
) -> SnapshotStore:
    return SnapshotStore(
        clock,
        max_tracks=max_tracks,
        max_detections=max_detections,
        track_stale_s=track_stale_s,
        detection_stale_s=detection_stale_s,
    )


def _make_sources(store: SnapshotStore) -> UISources:
    return UISources(snapshot=_FakeSnapshot(store), health=FakeHealth())


async def _make_client(
    store: SnapshotStore,
    *,
    token: str | None = None,
) -> TestClient:
    """Build an aiohttp TestClient against the console app (caller must close it)."""
    cfg = UIConfig(token=token)
    app = build_ui_app(_make_sources(store), cfg)
    client = TestClient(TestServer(app))
    await client.start_server()
    return client


def _pli_envelope(
    source_uid: str,
    *,
    ts: float,
    msg_id: str | None = None,
    lat: float = 38.5,
    lon: float = -122.5,
    hae: float = 0.0,
) -> Envelope:
    """Build a minimal PLI envelope with configurable position and timestamp."""
    return Envelope(
        msg_id=msg_id or f"pli-{source_uid}-{ts}",
        ts=ts,
        source_uid=source_uid,
        kind=MessageKind.PLI,
        payload={
            "node": {"uid": source_uid, "callsign": source_uid.upper(), "tier": "user"},
            "position": {"lat": lat, "lon": lon, "hae": hae},
        },
    )


def _marker_envelope(
    source_uid: str,
    *,
    msg_id: str,
    ts: float,
    track_id: int | None = None,
    label: str = "vehicle",
    confidence: float = 0.92,
) -> Envelope:
    """Build a minimal MARKER envelope with an optional composite track_id."""
    detection: dict[str, Any] = {"label": label, "confidence": confidence}
    if track_id is not None:
        detection["track_id"] = track_id
    return Envelope(
        msg_id=msg_id,
        ts=ts,
        source_uid=source_uid,
        kind=MessageKind.MARKER,
        payload={
            "node": {"uid": source_uid, "callsign": source_uid.upper(), "tier": "user"},
            "position": {"lat": 38.5, "lon": -122.5, "hae": 0.0},
            "detection": detection,
        },
    )


# ---------------------------------------------------------------------------
# S1 — Radio-silence TTL eviction (distinct from "no tracks")
#
# Validates that after radio silence exceeding ``track_stale_s``:
#   * The GeoJSON response is well-formed (not null, not a 5xx error).
#   * ``features`` is an empty list — not a missing key, not None.
#   * ``counters()["tracks_expired"]`` > 0, so a consumer can distinguish
#     "evicted due to staleness" from "no data ever received."
#   * The HTTP layer returns 200 (not an error state) even with zero features.
# ---------------------------------------------------------------------------


def test_s1_radio_silence_ttl_eviction_well_formed_empty_geojson() -> None:
    """S1a: After TTL, tracks_geojson returns well-formed empty FeatureCollection."""
    clock = FakeClock(t=0.0)
    store = _make_store(clock, track_stale_s=30.0)

    # Inject three tracks from three distinct sources.
    for i in range(3):
        store.handle(_pli_envelope(f"uas-{i}", ts=clock.t))

    # Confirm the tracks are initially present.
    fc_before = store.tracks_geojson()
    assert fc_before["type"] == "FeatureCollection"
    assert len(fc_before["features"]) == 3

    # Advance clock past TTL — simulates sustained radio silence.
    clock.t = 31.0  # > track_stale_s
    fc_after = store.tracks_geojson()

    # The response is well-formed: no null, no missing key, not an error shape.
    assert fc_after["type"] == "FeatureCollection"
    assert isinstance(fc_after["features"], list)
    assert len(fc_after["features"]) == 0


def test_s1_radio_silence_eviction_counter_distinguishes_from_never_received() -> None:
    """S1b: tracks_expired counter > 0 distinguishes staleness from empty-by-default."""
    clock = FakeClock(t=0.0)
    store = _make_store(clock, track_stale_s=10.0)

    # Baseline: counters before any data arrive (never-received state).
    baseline = store.counters()
    assert baseline["tracks_expired"] == 0
    assert baseline["tracks_live"] == 0

    store.handle(_pli_envelope("uas-alpha", ts=clock.t))

    clock.t = 15.0  # past TTL
    counters_after = store.counters()

    # Expired counter is non-zero — consumer can detect "we had data and lost it."
    assert counters_after["tracks_expired"] == 1
    assert counters_after["tracks_live"] == 0


@pytest.mark.asyncio
async def test_s1_http_returns_200_with_empty_features_after_ttl() -> None:
    """S1c: The HTTP /api/tracks endpoint returns 200 (not error) after full eviction."""
    clock = FakeClock(t=0.0)
    store = _make_store(clock, track_stale_s=5.0)
    store.handle(_pli_envelope("uas-bravo", ts=0.0))

    client = await _make_client(store)
    try:
        clock.t = 6.0  # expire everything before the HTTP request
        resp = await client.get("/api/tracks")
        assert resp.status == 200
        body = await resp.json()
        assert body["type"] == "FeatureCollection"
        assert body["features"] == []
    finally:
        await client.close()


# ---------------------------------------------------------------------------
# S2 — Multi-source composite-key concurrency (no composite-key collisions)
#
# ``track_id`` is per-source tracker numbering and is NOT globally unique
# (spec §2).  Two sources that both emit track_id=1 MUST remain two separate
# detection entries keyed by ``(source_uid, track_id)``.
# ---------------------------------------------------------------------------


def test_s2_concurrent_sources_same_track_id_no_collision() -> None:
    """S2a: ≥2 sources emitting the same track_id produce distinct entries."""
    clock = FakeClock(t=0.0)
    store = _make_store(clock)

    n_sources = 4  # ≥2 per the plan; 4 gives stronger coverage
    for source_idx in range(n_sources):
        store.handle(
            _marker_envelope(
                f"cam-{source_idx}",
                msg_id=f"det-src{source_idx}",
                ts=clock.t,
                track_id=1,  # same track_id across all sources
            )
        )

    features = store.detections_geojson()["features"]
    assert len(features) == n_sources, (
        f"Expected {n_sources} detections (one per source), "
        f"got {len(features)} — composite-key collision detected"
    )

    # Verify all source_uid values are present (no silent overwrite).
    source_uids = {f["properties"]["uid"] for f in features}
    assert source_uids == {f"cam-{i}" for i in range(n_sources)}


def test_s2_same_source_same_track_id_upserts_not_duplicates() -> None:
    """S2b: Same (source_uid, track_id) later in time upserts — no duplicate entries."""
    clock = FakeClock(t=0.0)
    store = _make_store(clock)

    store.handle(_marker_envelope("cam-0", msg_id="d1", ts=1.0, track_id=42))
    store.handle(_marker_envelope("cam-0", msg_id="d2", ts=2.0, track_id=42))

    features = store.detections_geojson()["features"]
    assert len(features) == 1, "Same (source_uid, track_id) must upsert, not duplicate"
    assert features[0]["properties"]["ts"] == 2.0


def test_s2_interleaved_multi_source_total_count_correct() -> None:
    """S2c: Interleaved envelopes from 3 sources × 3 track_ids = 9 distinct entries."""
    clock = FakeClock(t=0.0)
    store = _make_store(clock, max_detections=128)

    for src_idx in range(3):
        for tid in range(3):
            clock.t += 0.1
            store.handle(
                _marker_envelope(
                    f"cam-{src_idx}",
                    msg_id=f"m-{src_idx}-{tid}",
                    ts=clock.t,
                    track_id=tid,
                )
            )

    features = store.detections_geojson()["features"]
    assert len(features) == 9  # 3 sources × 3 track_ids, all distinct keys


# ---------------------------------------------------------------------------
# S3 — Cap eviction ordering under backpressure
#
# A deterministic (non-Hypothesis) scenario: inserting max+N entries must
# evict the *oldest* entries first and keep the cap strictly respected.
# The Hypothesis property tests already cover arbitrary interleavings; this
# named scenario pins the ordering contract with a readable, reproducible trace.
# ---------------------------------------------------------------------------


def test_s3_cap_eviction_oldest_first_tracks() -> None:
    """S3a: Inserting max_tracks+5 PLI entries evicts oldest-first; cap strictly held."""
    max_t = 8
    clock = FakeClock(t=0.0)
    store = _make_store(clock, max_tracks=max_t)

    # Insert max_t entries — all should be present.
    for i in range(max_t):
        clock.t = float(i)
        store.handle(_pli_envelope(f"uas-{i}", ts=clock.t))

    assert len(store.tracks_geojson()["features"]) == max_t

    # Insert 5 more — oldest (uas-0 through uas-4) must be evicted.
    overflow = 5
    for i in range(max_t, max_t + overflow):
        clock.t = float(i)
        store.handle(_pli_envelope(f"uas-{i}", ts=clock.t))

    features = store.tracks_geojson()["features"]
    assert len(features) == max_t, "Cap must not be exceeded after overflow"

    live_uids = {f["properties"]["uid"] for f in features}
    evicted_uids = {f"uas-{i}" for i in range(overflow)}      # oldest 5
    retained_uids = {f"uas-{i}" for i in range(overflow, max_t + overflow)}  # newest 8

    assert live_uids.isdisjoint(evicted_uids), "Oldest entries must have been evicted"
    assert retained_uids.issubset(live_uids), "Newest entries must be retained"


def test_s3_cap_eviction_counter_increments() -> None:
    """S3b: Eviction counters reflect the number of oldest-first ejections."""
    max_d = 4
    clock = FakeClock(t=0.0)
    store = _make_store(clock, max_detections=max_d)

    for i in range(max_d + 3):
        clock.t = float(i)
        store.handle(
            _marker_envelope("cam-0", msg_id=f"d{i}", ts=clock.t, track_id=i)
        )

    counters = store.counters()
    assert counters["detections_evicted"] == 3
    assert counters["detections_live"] == max_d


def test_s3_cap_never_exceeded_mixed_upserts_and_inserts() -> None:
    """S3c: Mixed upserts + new inserts never push the store past its cap."""
    max_t = 6
    clock = FakeClock(t=0.0)
    store = _make_store(clock, max_tracks=max_t)

    # Fill to cap.
    for i in range(max_t):
        store.handle(_pli_envelope(f"uas-{i}", ts=float(i)))

    # Upsert existing + add new (should evict one old for each new).
    for round_n in range(10):
        clock.t = float(max_t + round_n)
        store.handle(_pli_envelope("uas-0", ts=clock.t))       # upsert
        store.handle(_pli_envelope(f"new-{round_n}", ts=clock.t))  # new

    assert len(store.tracks_geojson()["features"]) <= max_t


# ---------------------------------------------------------------------------
# S4 — Kill-switch / freeze (update-loop halt; stable last-known state)
#
# Validates that when no new envelopes arrive (simulated by halting calls to
# ``handle``) AND the clock does not advance past the TTL, the existing snapshot
# continues to be served correctly via the HTTP layer.
#
# The xfail sub-test documents the currently-unimplemented ``X-Snapshot-Age``
# response header.  It will flip to xpass once the header is added to
# ``build_ui_app``'s ``/api/tracks`` (and ``/api/detections``) handlers.
# ---------------------------------------------------------------------------


def test_s4_frozen_update_loop_data_still_served() -> None:
    """S4a: After update-loop halt (no new handle calls), last snapshot is served."""
    clock = FakeClock(t=0.0)
    store = _make_store(clock, track_stale_s=600.0)

    uids = ["uas-alpha", "uas-beta", "uas-gamma"]
    for uid in uids:
        store.handle(_pli_envelope(uid, ts=clock.t))

    # Simulate update-loop halt: advance clock slightly but not past TTL;
    # make NO further handle() calls.
    clock.t = 5.0

    fc = store.tracks_geojson()
    assert fc["type"] == "FeatureCollection"
    live_uids = {f["properties"]["uid"] for f in fc["features"]}
    assert live_uids == set(uids), "All last-known tracks must still be present after freeze"


def test_s4_frozen_clock_prevents_ttl_eviction() -> None:
    """S4b: A frozen (non-advancing) clock never evicts entries via TTL sweep."""
    clock = FakeClock(t=0.0)
    store = _make_store(clock, track_stale_s=1.0)
    store.handle(_pli_envelope("uas-delta", ts=0.0))

    # Clock stays at 0.0 — sweep deadline is 0.0 - 1.0 = -1.0, so nothing expires.
    for _ in range(20):
        fc = store.tracks_geojson()
        assert len(fc["features"]) == 1, "Entry must not expire when clock is frozen"


@pytest.mark.asyncio
async def test_s4_http_serves_frozen_state() -> None:
    """S4c: The HTTP /api/tracks endpoint returns the frozen last-known state (200)."""
    clock = FakeClock(t=0.0)
    store = _make_store(clock, track_stale_s=600.0)
    store.handle(_pli_envelope("uas-foxtrot", ts=0.0))

    client = await _make_client(store)
    try:
        clock.t = 10.0  # time passes but well within TTL

        # First request — data present.
        resp1 = await client.get("/api/tracks")
        assert resp1.status == 200
        body1 = await resp1.json()
        assert len(body1["features"]) == 1

        # No new handle() calls — second request still returns last-known state.
        clock.t = 20.0
        resp2 = await client.get("/api/tracks")
        assert resp2.status == 200
        body2 = await resp2.json()
        assert len(body2["features"]) == 1
        assert body2["features"][0]["properties"]["uid"] == "uas-foxtrot"
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.xfail(
    reason=(
        "X-Snapshot-Age response header not yet implemented in build_ui_app. "
        "Add 'X-Snapshot-Age: <seconds>' to /api/tracks and /api/detections responses "
        "so clients can distinguish a frozen snapshot from a live one. "
        "This xfail will flip to xpass once the header is added."
    ),
    strict=True,
)
async def test_s4_snapshot_age_header_present() -> None:
    """S4d (xfail): /api/tracks includes X-Snapshot-Age to signal frozen state."""
    clock = FakeClock(t=0.0)
    store = _make_store(clock, track_stale_s=600.0)
    store.handle(_pli_envelope("uas-golf", ts=0.0))

    client = await _make_client(store)
    try:
        clock.t = 30.0
        resp = await client.get("/api/tracks")
        assert resp.status == 200
        # The header must be present and parse as a non-negative float.
        age_header = resp.headers.get("X-Snapshot-Age")
        assert age_header is not None, "X-Snapshot-Age header must be present"
        age = float(age_header)
        assert age >= 0.0
    finally:
        await client.close()


# ---------------------------------------------------------------------------
# S5 — Cache-Control: no-store on ALL token-bearing responses
#
# The page route already has this header (tested in test_ui_app.py).  This
# scenario asserts it extends to every /api/* route — a browser or caching
# proxy that caches a JSON response containing the bearer token would expose
# the token to the next visitor of the same cached URL.
# ---------------------------------------------------------------------------

_ALL_API_GET_PATHS = [
    "/api/tracks",
    "/api/detections",
    "/api/health",
]

_TOKEN = "s3cr3t-tok3n"


@pytest.mark.asyncio
@pytest.mark.parametrize("path", _ALL_API_GET_PATHS)
async def test_s5_no_store_header_on_api_routes(path: str) -> None:
    """S5a: Every /api/* GET response includes Cache-Control: no-store."""
    clock = FakeClock(t=0.0)
    store = _make_store(clock)
    client = await _make_client(store, token=_TOKEN)
    try:
        resp = await client.get(path, headers={"Authorization": f"Bearer {_TOKEN}"})
        assert resp.status == 200, f"Expected 200 on {path}, got {resp.status}"
        cc = resp.headers.get("Cache-Control", "")
        assert "no-store" in cc, (
            f"Cache-Control: no-store missing on {path}; got {cc!r}. "
            "A caching proxy could persist the bearer token to disk."
        )
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_s5_no_store_on_page_with_token_query() -> None:
    """S5b: The page served with ?token=... also includes Cache-Control: no-store."""
    clock = FakeClock(t=0.0)
    store = _make_store(clock)
    client = await _make_client(store, token=_TOKEN)
    try:
        resp = await client.get("/", params={"token": _TOKEN})
        assert resp.status == 200
        cc = resp.headers.get("Cache-Control", "")
        assert "no-store" in cc, (
            f"Cache-Control: no-store missing on token-gated page; got {cc!r}"
        )
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_s5_healthz_no_cache_not_required_but_no_sensitive_data() -> None:
    """S5c: /healthz is open (no token) and discloses nothing sensitive."""
    clock = FakeClock(t=0.0)
    store = _make_store(clock)
    client = await _make_client(store, token=_TOKEN)
    try:
        # /healthz is always open — no auth header needed.
        resp = await client.get("/healthz")
        assert resp.status == 200
        body = await resp.json()
        # Must not leak token material or position data.
        body_text = str(body)
        assert _TOKEN not in body_text
        assert "lat" not in body_text and "lon" not in body_text
    finally:
        await client.close()


# ---------------------------------------------------------------------------
# S6 — Stale-token rejection after rotation
#
# Simulates a token rotation by building two app instances with different
# tokens.  The old token must be rejected by the new instance (401) and the
# new token must work.  A single app instance's old token is always the same
# object — "rotation" is defined here as deploying a new app with a new token,
# which is the real operational meaning of token rotation for this service.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_s6_old_token_rejected_after_rotation() -> None:
    """S6a: An old bearer token returns 401 after the service is restarted with a new token."""
    old_token = "old-tok-alpha"
    new_token = "new-tok-beta"

    clock = FakeClock(t=0.0)
    store = _make_store(clock)

    # Phase 1: service is running with old_token.
    cfg_old = UIConfig(token=old_token)
    app_old = build_ui_app(_make_sources(store), cfg_old)
    client_old = TestClient(TestServer(app_old))
    await client_old.start_server()
    try:
        resp = await client_old.get(
            "/api/tracks", headers={"Authorization": f"Bearer {old_token}"}
        )
        assert resp.status == 200, "Old token must work on the old instance"
    finally:
        await client_old.close()

    # Phase 2: service is restarted with new_token (new app instance).
    cfg_new = UIConfig(token=new_token)
    app_new = build_ui_app(_make_sources(store), cfg_new)
    client_new = TestClient(TestServer(app_new))
    await client_new.start_server()
    try:
        # Old token → rejected.
        resp_old = await client_new.get(
            "/api/tracks", headers={"Authorization": f"Bearer {old_token}"}
        )
        assert resp_old.status == 401, "Old token must be rejected after rotation"

        # New token → accepted.
        resp_new = await client_new.get(
            "/api/tracks", headers={"Authorization": f"Bearer {new_token}"}
        )
        assert resp_new.status == 200, "New token must work after rotation"
    finally:
        await client_new.close()


@pytest.mark.asyncio
async def test_s6_stale_token_body_reveals_no_data() -> None:
    """S6b: A 401 response from a rotated token leaks zero track/detection data."""
    clock = FakeClock(t=0.0)
    store = _make_store(clock)
    store.handle(_pli_envelope("uas-hotel", ts=0.0))

    client = await _make_client(store, token="live-token")
    try:
        resp = await client.get(
            "/api/tracks", headers={"Authorization": "Bearer stale-token"}
        )
        assert resp.status == 401
        body = await resp.json()
        # The error body must not contain any feature data.
        body_text = str(body)
        assert "FeatureCollection" not in body_text
        assert "features" not in body_text
        assert "uas-hotel" not in body_text
    finally:
        await client.close()


# ---------------------------------------------------------------------------
# Supplemental: whitelist-boundary log-ring soak helper
#
# This is not a scenario test that runs in normal CI — it is the automated
# scanner referenced in Gate 3 / F3 of the field validation plan.  It is
# provided here as a reusable callable so the soak script can import it:
#
#   from test_ui_validation_scenarios import assert_logring_whitelist
#   assert_logring_whitelist(entries)
# ---------------------------------------------------------------------------


def assert_logring_whitelist(entries: list[dict[str, Any]], *, token: str = "") -> None:
    """Assert that a dumped log-ring buffer respects the whitelist boundary.

    Call this after a soak run with the output of ``LogRing.entries()``.  Raises
    ``AssertionError`` with a specific message on the first violation found.

    Checks enforced:
    * No entry contains ``token`` (when provided) as a substring of any value.
    * Every value in every entry is a JSON-safe scalar (str, int, float, bool, None).
    * No float value is NaN or ±infinity (not valid JSON).
    """
    import math

    SCALAR_TYPES = (str, int, float, bool, type(None))

    for idx, entry in enumerate(entries):
        for key, value in entry.items():
            # Non-scalar check
            if not isinstance(value, SCALAR_TYPES):
                raise AssertionError(
                    f"Entry[{idx}] key {key!r} has non-scalar value {type(value).__name__!r}; "
                    "only JSON-safe scalars are allowed in the log ring"
                )
            # NaN/inf check
            if isinstance(value, float) and not math.isfinite(value):
                raise AssertionError(
                    f"Entry[{idx}] key {key!r} contains non-finite float {value!r}; "
                    "NaN/inf are not valid JSON"
                )
            # Token-leak check
            if token and isinstance(value, str) and token in value:
                raise AssertionError(
                    f"Entry[{idx}] key {key!r} contains the bearer token — "
                    "the no-secrets-in-logs discipline has been violated"
                )


def test_assert_logring_whitelist_passes_on_clean_entries() -> None:
    """The soak helper passes on well-formed scalar-only entries."""
    clean = [
        {"ts": 1.0, "level": "info", "event": "boot", "host": "localhost", "ok": True},
        {"ts": 2.0, "level": "warning", "event": "slow_poll", "latency_ms": 350},
    ]
    assert_logring_whitelist(clean, token="s3cr3t")


def test_assert_logring_whitelist_rejects_nonscalar() -> None:
    bad = [{"ts": 1.0, "event": "boot", "detail": {"nested": "object"}}]
    with pytest.raises(AssertionError, match="non-scalar"):
        assert_logring_whitelist(bad)


def test_assert_logring_whitelist_rejects_nonfinite_float() -> None:
    bad = [{"ts": float("nan"), "event": "boot"}]
    with pytest.raises(AssertionError, match="non-finite"):
        assert_logring_whitelist(bad)


def test_assert_logring_whitelist_rejects_token_leak() -> None:
    token = "super-secret"
    bad = [{"ts": 1.0, "event": f"request from {token}"}]
    with pytest.raises(AssertionError, match="bearer token"):
        assert_logring_whitelist(bad, token=token)
