"""Read-only LLM situational-awareness assistant for the drone comms unit.

A small, optional layer (install the ``[llm]`` extra) that lets an operator ask
natural-language questions about live drone telemetry and TAK tracks. It is
strictly advisory: every tool is read-only, so the assistant can observe and
summarize but never command the vehicle or alter the SA picture.

Public surface:
  * :class:`~meshsa.llm.sources.DroneState`, :class:`~meshsa.llm.sources.Track`
    and the ``TelemetrySource`` / ``TrackSource`` protocols (+ ``Static*`` and
    HTTP implementations).
  * :class:`~meshsa.llm.tools.ToolDispatcher` and :func:`~meshsa.llm.tools.tool_specs`.
  * :class:`~meshsa.llm.agent.SAAgent` and :func:`~meshsa.llm.agent.build_agent`.
  * :func:`~meshsa.llm.server.build_app` / :func:`~meshsa.llm.server.chat_reply`.
"""

from __future__ import annotations

from .agent import DEFAULT_MODEL, AgentReply, SAAgent, build_agent
from .server import ServerConfig, chat_reply, resolve_config
from .sources import (
    DroneState,
    FtsTrackSource,
    Mavlink2RestSource,
    StaticTelemetrySource,
    StaticTrackSource,
    TelemetrySource,
    Track,
    TrackSource,
    parse_fts_tracks,
    parse_global_position_int,
)
from .tools import ToolDispatcher, ToolResult, format_drone_state, format_tracks, tool_specs

__all__ = [
    "DEFAULT_MODEL",
    "AgentReply",
    "DroneState",
    "FtsTrackSource",
    "Mavlink2RestSource",
    "SAAgent",
    "ServerConfig",
    "StaticTelemetrySource",
    "StaticTrackSource",
    "TelemetrySource",
    "ToolDispatcher",
    "ToolResult",
    "Track",
    "TrackSource",
    "build_agent",
    "chat_reply",
    "format_drone_state",
    "format_tracks",
    "parse_fts_tracks",
    "parse_global_position_int",
    "resolve_config",
    "tool_specs",
]
