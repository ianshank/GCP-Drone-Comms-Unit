"""Unit tests for the read-only SA data sources and wire parsers."""

from __future__ import annotations

import math

import pytest

from meshsa.llm.sources import (
    DroneState,
    StaticTelemetrySource,
    StaticTrackSource,
    Track,
    _as_float,
    parse_fts_tracks,
    parse_global_position_int,
)


def test_parse_global_position_int_scales_fields() -> None:
    payload = {
        "message": {
            "type": "GLOBAL_POSITION_INT",
            "lat": 373000000,
            "lon": -1220000000,
            "alt": 100000,
            "relative_alt": 50000,
            "vx": 300,
            "vy": 400,
            "hdg": 18000,
        }
    }
    state = parse_global_position_int(payload, "uav-7")
    assert state.uid == "uav-7"
    assert state.lat == pytest.approx(37.3)
    assert state.lon == pytest.approx(-122.0)
    assert state.alt_m == pytest.approx(100.0)
    assert state.relative_alt_m == pytest.approx(50.0)
    # ground speed = hypot(3 m/s, 4 m/s) = 5 m/s
    assert state.ground_speed_ms == pytest.approx(5.0)
    assert state.heading_deg == pytest.approx(180.0)
    assert state.link_ok is True


def test_parse_global_position_int_accepts_bare_message() -> None:
    # No "message" envelope; values read directly off the mapping.
    state = parse_global_position_int({"lat": 0, "lon": 0}, "x")
    assert state.lat == 0.0 and state.lon == 0.0


def test_parse_global_position_int_heading_sentinel_is_unknown() -> None:
    state = parse_global_position_int({"hdg": 65535}, "x")
    assert state.heading_deg is None


def test_parse_global_position_int_missing_velocity_has_no_speed() -> None:
    state = parse_global_position_int({"vx": 100}, "x")  # vy missing
    assert state.ground_speed_ms is None


def test_as_float_rejects_bool_and_strings() -> None:
    assert _as_float(True) is None
    assert _as_float("nope") is None
    assert _as_float(None) is None
    assert _as_float(3) == 3.0
    assert _as_float(2.5) == 2.5


def test_parse_fts_tracks_from_list() -> None:
    data = [
        {"uid": "T1", "callsign": "ALPHA", "type": "a-f-G", "lat": 1.0, "lon": 2.0, "stale": 15},
        {"id": "T2", "latitude": 3.0, "longitude": 4.0},
        "garbage",  # skipped
        {"no_uid": True},  # skipped (no identifier)
    ]
    tracks = parse_fts_tracks(data)
    assert [t.uid for t in tracks] == ["T1", "T2"]
    assert tracks[0].callsign == "ALPHA"
    assert tracks[0].cot_type == "a-f-G"
    assert tracks[0].stale_s == 15.0
    assert tracks[1].lat == 3.0 and tracks[1].lon == 4.0


def test_parse_fts_tracks_from_wrapped_dict() -> None:
    tracks = parse_fts_tracks({"results": [{"uid": "Z"}]})
    assert len(tracks) == 1 and tracks[0].uid == "Z"


def test_parse_fts_tracks_unknown_shapes_yield_empty() -> None:
    assert parse_fts_tracks({"unexpected": 1}) == []
    assert parse_fts_tracks(42) == []
    assert parse_fts_tracks({"results": "notalist"}) == []


async def test_static_telemetry_source_roundtrip() -> None:
    src = StaticTelemetrySource(DroneState(uid="a"))
    assert (await src.drone_state()).uid == "a"
    src.set_state(DroneState(uid="b", alt_m=10))
    again = await src.drone_state()
    assert again.uid == "b" and again.alt_m == 10


async def test_static_track_source_roundtrip_and_copy() -> None:
    src = StaticTrackSource()
    assert await src.tracks() == []
    src.set_tracks([Track(uid="t")])
    out = await src.tracks()
    assert [t.uid for t in out] == ["t"]
    out.clear()  # returned list is a copy; internal state unchanged
    assert len(await src.tracks()) == 1


def test_ground_speed_math_is_euclidean() -> None:
    state = parse_global_position_int({"vx": 600, "vy": 800}, "x")
    assert state.ground_speed_ms == pytest.approx(math.hypot(6.0, 8.0))
