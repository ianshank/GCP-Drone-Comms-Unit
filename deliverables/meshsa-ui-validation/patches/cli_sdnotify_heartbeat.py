"""Gate 0.1 patch — sd_notify heartbeat instrumentation for meshsa.ui.cli.

This module documents the exact changes needed to ``packages/meshsa/src/meshsa/
ui/cli.py`` to make ``WatchdogSec=30`` in the systemd unit actually functional.

Background (from the peer review):
    ``WatchdogSec`` is silently inert when ``Type=simple`` is used — systemd
    never opens the sd_notify socket, so ``sd_notify(WATCHDOG=1)`` is a no-op.
    Switching to ``Type=notify`` + sending ``READY=1`` (once) and
    ``WATCHDOG=1`` (periodically) makes the watchdog live: if the heartbeat
    stops, systemd sends SIGABRT and restarts the service.

Changes required in ``cli.py``:
    1. Add ``_send_notify`` and ``_watchdog_loop`` as module-level helpers
       (below the imports block, before ``_run``).
    2. In ``_run`` (``# pragma: no cover``):
       a. Send ``READY=1`` after ``TCPSite.start()``.
       b. Replace ``await asyncio.Event().wait()`` with
          ``await _watchdog_loop(ui.watchdog_heartbeat_s)``.

New UIConfig field (add to ``packages/meshsa/src/meshsa/ui/config.py``):
    ``watchdog_heartbeat_s: float = Field(default=10.0, gt=0.0)``
    Env binding: ``MESHSA_UI_WATCHDOG_HEARTBEAT_S``

    Default of 10 s is safely below ``WatchdogSec=30 / 2 = 15 s``, which is
    the maximum interval allowed by the sd_notify watchdog contract.

Dependency (add to ``packages/meshsa/pyproject.toml``):
    Under ``[project.optional-dependencies]`` add or extend:
        ``ui = ["aiohttp>=3.9", "sdnotify>=0.3"]``

    ``sdnotify`` is a minimal (~200 LoC) pure-Python package with no
    transitive deps.  It is a no-op when ``$NOTIFY_SOCKET`` is not set
    (outside systemd), so it is safe to import unconditionally.

Coverage note:
    ``_send_notify`` and ``_watchdog_loop`` are fully covered by
    ``test_cli_sdnotify.py``.  The live wiring in ``_run`` stays
    ``# pragma: no cover`` per CHARTER §4.6.
"""

from __future__ import annotations

import asyncio
import logging
import unittest.mock as mock

import pytest

_log = logging.getLogger("meshsa.ui.cli")

# ── Helper 1: _send_notify (add near the top of cli.py, after imports) ──────


def _send_notify(message: str) -> None:
    """Send an sd_notify message if the ``sdnotify`` package is available.

    Graceful fallback: when running outside systemd (``$NOTIFY_SOCKET``
    unset) or when the ``sdnotify`` package is not installed, this is a
    no-op.  The console operates correctly in both cases; only the watchdog
    gate in the systemd unit becomes inactive.

    Callers:
        * ``"READY=1"``   — sent once after the ``TCPSite`` is bound.
        * ``"WATCHDOG=1"`` — sent on each heartbeat iteration.
        * ``"STOPPING=1"`` — sent on graceful shutdown before awaiting cleanup.

    Args:
        message: An sd_notify protocol message string.
    """
    try:
        import sdnotify  # type: ignore[import]  # optional dependency

        notifier = sdnotify.SystemdNotifier()
        notifier.notify(message)
    except ImportError:
        _log.debug(
            "sdnotify not available; systemd watchdog inactive",
            extra={"hint": "pip install sdnotify  or  pip install 'meshsa[ui]'"},
        )
    except Exception as exc:
        # Never let a notification failure crash the service.
        _log.warning(
            "sd_notify failed",
            extra={"message": message, "error": str(exc)},
        )


# ── Helper 2: _watchdog_loop (add after _send_notify in cli.py) ─────────────


async def _watchdog_loop(interval_s: float) -> None:
    """Coroutine that sends ``WATCHDOG=1`` every ``interval_s`` seconds.

    Replace the original ``await asyncio.Event().wait()`` in ``_run`` with::

        await _watchdog_loop(ui.watchdog_heartbeat_s)

    where ``ui.watchdog_heartbeat_s`` defaults to ``10.0`` (safely below the
    ``WatchdogSec=30 / 2 = 15 s`` contract threshold).

    The loop exits only on ``asyncio.CancelledError`` (SIGINT / SIGTERM path),
    so the caller's ``finally`` block still runs cleanup.

    Args:
        interval_s: Seconds between heartbeats.  Must be less than
            ``WatchdogSec / 2`` from the systemd unit file.
    """
    try:
        while True:
            _send_notify("WATCHDOG=1")
            await asyncio.sleep(interval_s)
    except asyncio.CancelledError:
        _send_notify("STOPPING=1")
        raise  # re-raise so the caller's finally block runs


# ── Diff summary for _run (apply to packages/meshsa/src/meshsa/ui/cli.py) ───
#
# Only the lines marked + / - change; everything else stays identical.
#
# -    await asyncio.Event().wait()
# +    # Notify systemd the service is ready (Type=notify in meshsa-ui.service).
# +    _send_notify("READY=1")
# +    try:
# +        # Watchdog heartbeat loop — replaces the former indefinite wait.
# +        await _watchdog_loop(ui.watchdog_heartbeat_s)
# +    finally:
# +        _send_notify("STOPPING=1")
#          await runner.cleanup()
#          ...
#
# The ``_send_notify("STOPPING=1")`` in the finally block is the authoritative
# one for graceful shutdown.  ``_watchdog_loop`` also sends it on
# CancelledError, but the finally block ensures it is sent even if the loop
# raises a non-CancelledError exception.  Duplicate STOPPING=1 messages are
# harmless (systemd ignores them after the first).


# ── Unit tests (drop into packages/meshsa/tests/test_cli_sdnotify.py) ───────
#
# These functions are also present in the standalone test file
# test_cli_sdnotify.py in this deliverables package.  They are duplicated here
# so this patch module is self-documenting and independently runnable with:
#     pytest patches/cli_sdnotify_heartbeat.py -v


class TestSendNotifyPatch:
    """Smoke tests exercising the _send_notify contract from the patch file."""

    def test_ready_message_delivered(self) -> None:
        notifier = mock.MagicMock()
        fake_sdnotify = mock.MagicMock()
        fake_sdnotify.SystemdNotifier.return_value = notifier
        with mock.patch.dict(__import__("sys").modules, {"sdnotify": fake_sdnotify}):
            _send_notify("READY=1")
        notifier.notify.assert_called_once_with("READY=1")

    def test_missing_package_is_noop(self) -> None:
        with mock.patch.dict(__import__("sys").modules, {"sdnotify": None}):  # type: ignore[dict-item]
            _send_notify("READY=1")  # must not raise

    def test_notify_error_swallowed(self) -> None:
        notifier = mock.MagicMock()
        notifier.notify.side_effect = OSError("socket gone")
        fake_sdnotify = mock.MagicMock()
        fake_sdnotify.SystemdNotifier.return_value = notifier
        with mock.patch.dict(__import__("sys").modules, {"sdnotify": fake_sdnotify}):
            _send_notify("WATCHDOG=1")  # must not raise


class TestWatchdogLoopPatch:
    """Smoke tests for _watchdog_loop from the patch file."""

    @pytest.mark.asyncio
    async def test_sends_heartbeat_then_reraises_cancelled(self) -> None:
        sent: list[str] = []
        call_count = 0

        async def _fake_sleep(s: float) -> None:
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise asyncio.CancelledError

        with (
            mock.patch(f"{__name__}._send_notify", side_effect=sent.append),
            mock.patch("asyncio.sleep", side_effect=_fake_sleep),
        ):
            with pytest.raises(asyncio.CancelledError):
                await _watchdog_loop(interval_s=10.0)

        assert "WATCHDOG=1" in sent
        assert "STOPPING=1" in sent

    @pytest.mark.asyncio
    async def test_reraises_cancelled_error(self) -> None:
        with (
            mock.patch(f"{__name__}._send_notify"),
            mock.patch("asyncio.sleep", side_effect=asyncio.CancelledError),
        ):
            with pytest.raises(asyncio.CancelledError):
                await _watchdog_loop(interval_s=10.0)
