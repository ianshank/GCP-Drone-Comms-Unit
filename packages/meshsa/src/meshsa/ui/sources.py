"""Injectable data-source seams for the operator console (spec §3, design D-7).

Every panel reads through a ``Protocol`` so the app factory is tested entirely with fakes
(CHARTER §4.3: DI via Protocol, tests need no hardware). ``UISources`` carries the wired
set; every optional source degrades by omission — an absent source means its route is not
registered and its panel is left out of the page manifest (the fpv-optional precedent).

The concrete adapters wrap existing, already-tested seams (nothing here re-implements
them): ``health_snapshot``/``render_metrics``, ``LinkHealthMonitor.evaluate`` and the llm
``chat_reply`` policy (generic 502 to the browser, detail logged server-side).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

from ..health import health_snapshot, render_metrics

if TYPE_CHECKING:
    from ..node import Node

__all__ = [
    "SnapshotSource",
    "HealthSource",
    "FpvSource",
    "ChatBackend",
    "LogSource",
    "UISources",
    "NodeHealthSource",
    "FpvLinkSource",
    "AgentChatBackend",
]


@runtime_checkable
class SnapshotSource(Protocol):
    """The current tactical picture (implemented by :class:`meshsa.ui.snapshot.SnapshotStore`)."""

    def tracks_geojson(self) -> dict[str, Any]: ...

    def detections_geojson(self) -> dict[str, Any]: ...

    def counters(self) -> dict[str, int]: ...


@runtime_checkable
class HealthSource(Protocol):
    """Node health + metrics for the status panel."""

    def snapshot(self) -> dict[str, Any]: ...


@runtime_checkable
class FpvSource(Protocol):
    """FPV link-health strip (optional; requires the ``[fpv]`` extra at wiring time)."""

    def report(self) -> dict[str, Any]: ...


@runtime_checkable
class ChatBackend(Protocol):
    """Read-only assistant seam (optional). MUST expose no command/mutation tools (I-2)."""

    async def reply(self, payload: Any) -> tuple[dict[str, Any], int]: ...


@runtime_checkable
class LogSource(Protocol):
    """Bounded log tail (optional; implemented by :class:`meshsa.ui.logring.LogRing`)."""

    def entries(self) -> list[dict[str, Any]]: ...


@dataclass
class UISources:
    """The wired source set consumed by ``build_ui_app``; ``None`` = panel absent."""

    snapshot: SnapshotSource
    health: HealthSource | None = None
    fpv: FpvSource | None = None
    chat: ChatBackend | None = None
    logs: LogSource | None = None


@dataclass
class NodeHealthSource:
    """Adapter over the in-process health seams (``meshsa.health``); no second listener."""

    node: Node
    metrics_format: Literal["prometheus", "json"] = "json"

    def snapshot(self) -> dict[str, Any]:
        return {
            "health": health_snapshot(self.node),
            "metrics": render_metrics(self.node, self.metrics_format),
        }


class _LinkHealthMonitor(Protocol):
    """Structural view of :class:`meshsa.fpv.link_health.LinkHealthMonitor` (no [fpv] import)."""

    def evaluate(self) -> Any: ...


@dataclass
class FpvLinkSource:
    """Adapter over ``LinkHealthMonitor.evaluate()`` -> a JSON-able report dict."""

    monitor: _LinkHealthMonitor

    def report(self) -> dict[str, Any]:
        report = self.monitor.evaluate()
        return {
            "state": report.state.value,
            "arm_permitted": report.arm_permitted,
            "reasons": list(report.reasons),
            "t_mono": report.t_mono,
        }


@dataclass
class AgentChatBackend:
    """Read-only assistant: delegates to the llm agent via the tested ``chat_reply`` policy.

    In-process (one origin, one token — design D-4); inherits the llm error posture:
    invalid payloads get a 400, upstream failures a **generic** 502 with the detail logged
    server-side only. The agent seam answers questions and mutates nothing; no
    command/mutation tools are exposed through this backend (I-2).
    """

    agent: Any
    max_prompt_chars: int = field(default=0)

    def __post_init__(self) -> None:
        if self.max_prompt_chars <= 0:
            from ..llm.server import DEFAULT_MAX_PROMPT_CHARS

            self.max_prompt_chars = DEFAULT_MAX_PROMPT_CHARS

    async def reply(self, payload: Any) -> tuple[dict[str, Any], int]:
        from ..llm.server import chat_reply

        return await chat_reply(self.agent, payload, max_prompt_chars=self.max_prompt_chars)
