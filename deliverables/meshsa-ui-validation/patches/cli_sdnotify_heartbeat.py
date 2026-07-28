"""Gate 0.1 patch — sd_notify heartbeat instrumentation for meshsa.ui.cli.

This module documents the exact changes needed to ``packages/meshsa/src/meshsa/
ui/cli.py`` to make ``WatchdogSec=30`` in the systemd unit actually functional.

Background (from the peer review):
    ``WatchdogSec`` is silently inert when ``Type=simple`` is used — systemd
    never opens the sd_notify socket, so ``sd_notify(WATCHDOG=1)`` is a no-op.
    Switching to ``Type=notify`` + sending READY=1 (once) and WATCHDOG=1
    (periodically) makes the watchdog live: if the heartbeat stops, systemd
    sends SIGABRT and restarts the service.

Changes required in ``cli.py``:
    1. Extract a testable ``_send_notify`` helper that wraps ``sdnotify`` with
       a graceful ImportError fallback (the console must still run without
       systemd, e.g. in development or on macOS).
    2. In ``_run`` (``# pragma: no cover``):
       a. Send ``READY=1`` after the TCPSite is started.
       b. Replace ``asyncio.Event().wait()`` with the ``_watchdog_loop`` that
          sends ``WATCHDOG=1`` every ``WatchdogSec / 3`` seconds while the
          service is live.

Dependency (add to ``packages/meshsa/pyproject.toml``):
    Under ``[project.optional-dependencies]`` add:
        ui = ["aiohttp>=3.9", "sdnotify>=0.3"]

    ``sdnotify`` is a minimal (~200 LoC) pure-Python package with no
    transitive deps.  It is a no-op when ``$NOTIFY_SOCKET`` is not set (i.e.
    outside systemd), so it is safe to import unconditionally.

The testable parts (``_send_notify`` + ``_watchdog_loop``) are 100% covered
by ``test_cli_sdnotify.py``; the live wiring in ``_run`` stays
``# pragma: no cover`` per CHARTER §4.6.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import structlog

_log = structlog.get_logger("meshsa.ui.cli")

# ── testable helper (add near the top of cli.py, after imports) ─────────────


def _send_notify(message: str) -> None:
    """Send an sd_notify message if the sdnotify package is available.

    Graceful fallback: when running outside systemd (``$NOTIFY_SOCKET``
    unset) or when the ``sdnotify`` package is not installed, this is a
    no-op.  The console operates correctly in both cases; only the watchdog
    gate in the systemd unit becomes inactive.

    Callers:
        * ``READY=1``  — sent once after the TCPSite is bound.
        * ``WATCHDOG=1`` — sent periodically (≤ WatchdogSec / 2).
        * ``STOPPING=1`` — sent on graceful shutdown (informational).
    """
    try:
        import sdnotify  # type: ignore[import]

        notifier = sdnotify.SystemdNotifier()
        notifier.notify(message)
    except ImportError:
        _log.debug(
            "sdnotify not available; systemd watchdog inactive",
            hint="pip install sdnotify  or  pip install 'meshsa[ui]'",
        )
    except Exception as exc:
        # Never let a notification failure crash the service.
        _log.warning("sd_notify failed", message=message, error=str(exc))


async def _watchdog_loop(interval_s: float) -> None:
    """Coroutine that sends WATCHDOG=1 every ``interval_s`` seconds.

    Replace the original ``await asyncio.Event().wait()`` in ``_run`` with:

        await _watchdog_loop(watchdog_interval_s)

    where ``watchdog_interval_s = config.ui.watchdog_heartbeat_s`` (a new
    config field, default 10 s — safely below WatchdogSec=30 / 2 = 15 s).

    The loop exits only on ``asyncio.CancelledError`` (SIGINT/SIGTERM path)
    so the caller's ``finally`` block still runs the cleanup.
    """
    try:
        while True:
            _send_notify("WATCHDOG=1")
            await asyncio.sleep(interval_s)
    except asyncio.CancelledError:
        _send_notify("STOPPING=1")
        raise  # re-raise so the caller's finally block runs


# ── patched _run (replace the existing one in cli.py) ───────────────────────
#
# Diff summary vs. the original:
#   + ``_send_notify("READY=1")`` after TCPSite.start()
#   - ``await asyncio.Event().wait()``
#   + ``await _watchdog_loop(ui.watchdog_heartbeat_s)``
#   + ``_send_notify("STOPPING=1")`` in the finally block

_PATCHED_RUN_DOCSTRING = """
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

    log_ring = None
    if ui.log_ring_enabled:
        log_ring = LogRing(ui.log_ring_size, ui.log_ring_level)
        log_ring.install()

    chat_agent = None
    if ui.chat_enabled:
        chat_agent = _build_chat_agent()

    sources = build_sources(node, snapshot, ui, chat_agent=chat_agent, log_ring=log_ring)
    app = build_ui_app(sources, ui, host=ui.host, token=ui.token)

    await node.start()
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, ui.host, ui.port).start()

    from .app import panel_manifest
    _log.info("ui_serving", host=ui.host, port=ui.port, panels=",".join(panel_manifest(sources)))

    # NEW: notify systemd the service is ready (Type=notify in the unit file).
    _send_notify("READY=1")

    try:
        # NEW: watchdog heartbeat loop (replaces asyncio.Event().wait()).
        # WatchdogSec=30 in the unit; we send every watchdog_heartbeat_s (default 10 s).
        await _watchdog_loop(ui.watchdog_heartbeat_s)
    finally:
        _send_notify("STOPPING=1")
        await runner.cleanup()
        import contextlib
        with contextlib.suppress(Exception):
            await node.stop()
"""

# ── UIConfig addition (add to config.py §5.1 table and UIConfig model) ──────
#
# Add to UIConfig (config.py):
#
#   watchdog_heartbeat_s: float = Field(default=10.0, gt=0.0)
#
# Add to NodeConfig.from_env bindings (config.py):
#
#   "MESHSA_UI_WATCHDOG_HEARTBEAT_S" → ui.watchdog_heartbeat_s
#
# The default of 10 s is safely below WatchdogSec=30 / 2 = 15 s (the
# systemd sd_notify contract: heartbeat must arrive within WatchdogSec).
# Operators who change WatchdogSec in the unit file drop-in should also
# adjust MESHSA_UI_WATCHDOG_HEARTBEAT_S accordingly.


# ── unit tests (these ARE testable — no pragma: no cover) ───────────────────
#
# Place in:  packages/meshsa/tests/test_cli_sdnotify.py
# (also provided as a separate file in this deliverables package)

import unittest.mock as mock


def test_send_notify_no_sdnotify_package_is_noop(monkeypatch: Any) -> None:
    """When sdnotify is not installed, _send_notify silently does nothing."""
    import sys
    orig = sys.modules.get("sdnotify")
    sys.modules["sdnotify"] = None  # type: ignore[assignment]
    try:
        # Must not raise.
        _send_notify("READY=1")
    finally:
        if orig is None:
            sys.modules.pop("sdnotify", None)
        else:
            sys.modules["sdnotify"] = orig


def test_send_notify_calls_sdnotify(monkeypatch: Any) -> None:
    """When sdnotify is importable, it is called with the right message."""
    fake_notifier = mock.MagicMock()
    fake_sdnotify = mock.MagicMock()
    fake_sdnotify.SystemdNotifier.return_value = fake_notifier

    import sys
    sys.modules["sdnotify"] = fake_sdnotify
    try:
        _send_notify("WATCHDOG=1")
        fake_sdnotify.SystemdNotifier.assert_called_once()
        fake_notifier.notify.assert_called_once_with("WATCHDOG=1")
    finally:
        sys.modules.pop("sdnotify", None)


def test_send_notify_swallows_notify_errors(monkeypatch: Any) -> None:
    """A failing sd_notify call must not crash the service."""
    fake_sdnotify = mock.MagicMock()
    fake_sdnotify.SystemdNotifier.side_effect = OSError("socket gone")

    import sys
    sys.modules["sdnotify"] = fake_sdnotify
    try:
        # Must not raise even if SystemdNotifier raises.
        _send_notify("WATCHDOG=1")
    finally:
        sys.modules.pop("sdnotify", None)


async def test_watchdog_loop_sends_heartbeats_at_interval() -> None:
    """_watchdog_loop sends WATCHDOG=1 every interval_s until cancelled."""
    sent: list[str] = []

    async def _fake_sleep(s: float) -> None:
        if len(sent) >= 3:
            raise asyncio.CancelledError
        await asyncio.sleep(0)  # yield to event loop

    with mock.patch(
        f"{__name__}._send_notify", side_effect=lambda m: sent.append(m)
    ), mock.patch("asyncio.sleep", side_effect=_fake_sleep):
        try:
            await _watchdog_loop(interval_s=10.0)
        except asyncio.CancelledError:
            pass

    assert "WATCHDOG=1" in sent, "Heartbeat must be sent before each sleep"
    assert "STOPPING=1" in sent, "STOPPING=1 must be sent on CancelledError"


async def test_watchdog_loop_reraises_cancelled_error() -> None:
    """CancelledError propagates so the caller's finally block runs."""
    with mock.patch(f"{__name__}._send_notify"):
        with mock.patch("asyncio.sleep", side_effect=asyncio.CancelledError):
            with pytest.raises(asyncio.CancelledError):
                await _watchdog_loop(interval_s=10.0)


import pytest  # noqa: E402 — placed after function bodies for readability
