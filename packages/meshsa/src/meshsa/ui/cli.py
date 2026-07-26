"""``meshsa-ui`` console entry point (spec §5.5).

The testable pieces (``build_sources``) live here as pure wiring logic; the live
orchestration (``main``/``_run`` — asyncio loop, node lifecycle, the aiohttp site) is
integration glue marked ``# pragma: no cover``, the only pragma in the ``ui`` package
(CHARTER §4.6). The serve loop is guarded transitively: ``build_ui_app`` imports and
calls the canonical ``meshsa.netauth.validate_bind`` before any route is wired (the
``scout/cli.py`` precedent; declared in ``.claude/governance.yaml``).
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING, Any

import structlog

from ..config import NodeConfig
from ..protocols import SystemClock
from .app import build_ui_app
from .config import UIConfig
from .logring import LogRing
from .snapshot import SnapshotStore
from .sources import AgentChatBackend, NodeHealthSource, UISources

if TYPE_CHECKING:
    from ..node import Node
    from .sources import LinkHealthMonitorLike

_log = structlog.get_logger("meshsa.ui.cli")

__all__ = ["build_sources", "main"]


def build_sources(
    node: Node,
    snapshot: SnapshotStore,
    config: UIConfig,
    *,
    fpv_monitor: LinkHealthMonitorLike | None = None,
    chat_agent: Any | None = None,
    log_ring: LogRing | None = None,
) -> UISources:
    """Wire the source set from config flags + available collaborators (pure, tested).

    Gating rules (design D-7; ``build_ui_app`` then treats presence as truth):

    * health — always wired (the node is a required collaborator);
    * fpv — wired iff ``fpv_monitor`` is provided (embedder-owned; no config flag);
    * chat — requires ``config.chat_enabled`` **and** a ``chat_agent``;
    * logs — requires ``config.log_ring_enabled`` **and** a ``log_ring``.

    ``fpv_monitor`` is a structural Protocol and ``chat_agent`` is the llm agent seam
    (typed ``Any`` in :class:`AgentChatBackend` too), so this stays testable with fakes
    and imports no optional extra.
    """
    from .sources import FpvLinkSource  # local: keeps the optional adapters together

    return UISources(
        snapshot=snapshot,
        health=NodeHealthSource(node, metrics_format=config.metrics_format),
        fpv=FpvLinkSource(fpv_monitor) if fpv_monitor is not None else None,
        chat=AgentChatBackend(chat_agent)
        if config.chat_enabled and chat_agent is not None
        else None,
        logs=log_ring if config.log_ring_enabled and log_ring is not None else None,
    )


def main() -> None:  # pragma: no cover - process entry point
    """Serve the operator console for a node configured from ``MESHSA_*`` env vars.

    Requires the ``[ui]`` extra (aiohttp). Fail-closed before any socket opens: the bind
    is validated inside ``build_ui_app``. The optional chat panel additionally needs the
    ``[llm]`` extra and its key; the FPV strip is wired by embedders that own a
    ``LinkHealthMonitor`` (this generic entry point serves map/health/logs).
    """
    try:
        import aiohttp  # noqa: F401  # presence check; web imported in _run
    except ImportError as exc:
        raise SystemExit(
            "meshsa-ui needs the optional [ui] extra (aiohttp).\n"
            "Install it with:  pip install -e 'packages/meshsa[ui]'\n"
            f"(missing dependency: {exc.name})"
        ) from exc

    config = NodeConfig.from_env()
    if not config.ui.enabled:
        raise SystemExit(
            "meshsa-ui is disabled; set MESHSA_UI_ENABLED=true (the console is off by default)"
        )
    asyncio.run(_run(config))


async def _run(config: NodeConfig) -> None:  # pragma: no cover - live wiring
    from aiohttp import web

    from ..node import build_node

    ui = config.ui
    node = build_node(config)
    snapshot = SnapshotStore(
        SystemClock(),
        max_tracks=ui.max_tracks,
        max_detections=ui.max_detections,
        track_stale_s=ui.track_stale_s,
        detection_stale_s=ui.detection_stale_s,
    )
    node.on_message(snapshot.handle)

    log_ring: LogRing | None = None
    if ui.log_ring_enabled:
        log_ring = LogRing(ui.log_ring_size, ui.log_ring_level)
        log_ring.install()

    chat_agent = None
    if ui.chat_enabled:
        chat_agent = _build_chat_agent()

    sources = build_sources(node, snapshot, ui, chat_agent=chat_agent, log_ring=log_ring)
    app = build_ui_app(sources, ui, host=ui.host, token=ui.token)  # fail-closed bind check

    await node.start()
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, ui.host, ui.port).start()
    from .app import panel_manifest

    _log.info("ui_serving", host=ui.host, port=ui.port, panels=",".join(panel_manifest(sources)))
    try:
        await asyncio.Event().wait()  # serve until cancelled (Ctrl-C)
    finally:
        await runner.cleanup()
        with contextlib.suppress(Exception):
            await node.stop()


def _build_chat_agent() -> object | None:  # pragma: no cover - optional [llm] wiring
    """Build the llm agent for the chat panel; ``None`` (panel off) when unavailable."""
    try:
        import os

        from ..llm.agent import build_agent
        from ..llm.server import resolve_config
        from ..llm.sources import FtsTrackSource, Mavlink2RestSource

        llm_cfg = resolve_config(os.environ)
        telemetry = Mavlink2RestSource(llm_cfg.mavlink2rest_url, uid=llm_cfg.drone_uid)
        tracks = FtsTrackSource(llm_cfg.fts_tracks_url)
        return build_agent(telemetry, tracks)
    except Exception as exc:
        _log.warning("ui_chat_unavailable", error=str(exc), error_type=type(exc).__name__)
        return None


if __name__ == "__main__":  # pragma: no cover
    main()
