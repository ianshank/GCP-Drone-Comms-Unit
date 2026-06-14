"""Unit tests for SA tool specs, formatters, and dispatch."""

from __future__ import annotations

from meshsa.llm.sources import DroneState, StaticTelemetrySource, StaticTrackSource, Track
from meshsa.llm.tools import (
    GET_DRONE_STATE,
    LIST_TRACKS,
    ToolDispatcher,
    format_drone_state,
    format_tracks,
    tool_specs,
)


def test_tool_specs_are_well_formed() -> None:
    specs = tool_specs()
    names = {s["name"] for s in specs}
    assert names == {GET_DRONE_STATE, LIST_TRACKS}
    for spec in specs:
        assert spec["description"]
        schema = spec["input_schema"]
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False


def test_format_drone_state_full() -> None:
    state = DroneState(
        uid="uav-1",
        lat=37.0,
        lon=-122.0,
        relative_alt_m=42.5,
        ground_speed_ms=5.0,
        heading_deg=90.0,
        battery_pct=88.0,
        armed=True,
        mode="GUIDED",
    )
    out = format_drone_state(state)
    assert "uav-1" in out
    assert "37.000000, -122.000000" in out
    assert "relative alt 42.5 m" in out
    assert "ground speed 5.0 m/s" in out
    assert "heading 90 deg" in out
    assert "battery 88%" in out
    assert "ARMED" in out
    assert "mode GUIDED" in out


def test_format_drone_state_uses_amsl_when_no_relative() -> None:
    out = format_drone_state(DroneState(uid="x", alt_m=120.0))
    assert "alt 120.0 m AMSL" in out


def test_format_drone_state_disarmed_and_empty() -> None:
    assert "disarmed" in format_drone_state(DroneState(uid="x", armed=False))
    assert "no telemetry fields populated yet" in format_drone_state(DroneState(uid="x"))


def test_format_drone_state_link_down() -> None:
    out = format_drone_state(DroneState(uid="x", link_ok=False))
    assert "link DOWN" in out


def test_format_tracks_empty_and_populated() -> None:
    assert "no active tracks" in format_tracks([])
    out = format_tracks(
        [
            Track(uid="T1", callsign="ALPHA", cot_type="a-f-G", lat=1.0, lon=2.0, stale_s=15),
            Track(uid="T2"),
        ]
    )
    assert "2 active track(s)" in out
    assert "ALPHA" in out
    assert "type a-f-G" in out
    assert "at 1.00000, 2.00000" in out
    assert "stale 15s" in out
    assert "T2" in out  # falls back to uid when no callsign


async def test_dispatcher_get_drone_state() -> None:
    disp = ToolDispatcher(
        StaticTelemetrySource(DroneState(uid="uav-1", relative_alt_m=10.0)),
        StaticTrackSource(),
    )
    assert disp.names == (GET_DRONE_STATE, LIST_TRACKS)
    result = await disp.dispatch(GET_DRONE_STATE, {})
    assert result.is_error is False
    assert "uav-1" in result.content


async def test_dispatcher_list_tracks() -> None:
    disp = ToolDispatcher(
        StaticTelemetrySource(DroneState(uid="x")),
        StaticTrackSource([Track(uid="T1", callsign="BRAVO")]),
    )
    result = await disp.dispatch(LIST_TRACKS, {})
    assert "BRAVO" in result.content


async def test_dispatcher_unknown_tool_is_error() -> None:
    disp = ToolDispatcher(StaticTelemetrySource(DroneState(uid="x")), StaticTrackSource())
    result = await disp.dispatch("frobnicate", {})
    assert result.is_error is True
    assert "unknown tool" in result.content
