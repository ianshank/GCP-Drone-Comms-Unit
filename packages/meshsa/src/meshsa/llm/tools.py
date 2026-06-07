"""Tool definitions and dispatch for the SA assistant.

The assistant is given a small, **read-only** tool surface over the
``TelemetrySource`` / ``TrackSource`` protocols. Tool schemas (``tool_specs``)
and the human-readable formatters are pure; ``ToolDispatcher`` is async only
because the sources are, and it is fully testable with the in-memory
``Static*`` sources — no network, no LLM.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

from .sources import DroneState, TelemetrySource, Track, TrackSource

GET_DRONE_STATE = "get_drone_state"
LIST_TRACKS = "list_tracks"


class ToolResult(BaseModel):
    """Outcome of one tool call: text content plus an error flag for the API."""

    content: str
    is_error: bool = False


def tool_specs() -> list[dict[str, Any]]:
    """Return the Anthropic tool definitions for the read-only SA tools.

    Descriptions are prescriptive about *when* to call each tool — current Opus
    models reach for tools conservatively, so the trigger condition lives in the
    description, not just the system prompt.
    """
    return [
        {
            "name": GET_DRONE_STATE,
            "description": (
                "Get the connected drone's current telemetry: position "
                "(lat/lon), altitude, ground speed, heading, battery, armed "
                "state, and flight mode. Call this whenever the user asks about "
                "the drone's location, altitude, speed, battery, or status."
            ),
            "input_schema": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
        {
            "name": LIST_TRACKS,
            "description": (
                "List the situational-awareness tracks currently on the TAK / "
                "ATAK network (callsign, CoT type, position). Call this when the "
                "user asks what units, contacts, or tracks are visible, or for a "
                "summary of the current picture."
            ),
            "input_schema": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    ]


def format_drone_state(state: DroneState) -> str:
    """Render a ``DroneState`` as a compact, LLM-friendly line list (pure)."""
    if not state.link_ok:
        return f"drone {state.uid}: telemetry link DOWN (no data available)"
    parts: list[str] = [f"drone {state.uid}:"]
    if state.lat is not None and state.lon is not None:
        parts.append(f"position {state.lat:.6f}, {state.lon:.6f}")
    if state.relative_alt_m is not None:
        parts.append(f"relative alt {state.relative_alt_m:.1f} m")
    elif state.alt_m is not None:
        parts.append(f"alt {state.alt_m:.1f} m AMSL")
    if state.ground_speed_ms is not None:
        parts.append(f"ground speed {state.ground_speed_ms:.1f} m/s")
    if state.heading_deg is not None:
        parts.append(f"heading {state.heading_deg:.0f} deg")
    if state.battery_pct is not None:
        parts.append(f"battery {state.battery_pct:.0f}%")
    if state.armed is not None:
        parts.append("ARMED" if state.armed else "disarmed")
    if state.mode is not None:
        parts.append(f"mode {state.mode}")
    if len(parts) == 1:
        parts.append("no telemetry fields populated yet")
    return " | ".join(parts)


def format_tracks(tracks: list[Track]) -> str:
    """Render a track list as a compact, LLM-friendly summary (pure)."""
    if not tracks:
        return "no active tracks on the TAK network"
    lines = [f"{len(tracks)} active track(s):"]
    for track in tracks:
        label = track.callsign or track.uid
        bits = [label]
        if track.cot_type:
            bits.append(f"type {track.cot_type}")
        if track.lat is not None and track.lon is not None:
            bits.append(f"at {track.lat:.5f}, {track.lon:.5f}")
        if track.stale_s is not None:
            bits.append(f"stale {track.stale_s:.0f}s")
        lines.append("  - " + ", ".join(bits))
    return "\n".join(lines)


class ToolDispatcher:
    """Route a tool call to the read-only data sources and format the result."""

    def __init__(self, telemetry: TelemetrySource, tracks: TrackSource) -> None:
        self._telemetry = telemetry
        self._tracks = tracks

    @property
    def names(self) -> tuple[str, ...]:
        return (GET_DRONE_STATE, LIST_TRACKS)

    async def dispatch(self, name: str, _args: Mapping[str, Any]) -> ToolResult:
        if name == GET_DRONE_STATE:
            return ToolResult(content=format_drone_state(await self._telemetry.drone_state()))
        if name == LIST_TRACKS:
            return ToolResult(content=format_tracks(await self._tracks.tracks()))
        return ToolResult(content=f"unknown tool: {name}", is_error=True)
