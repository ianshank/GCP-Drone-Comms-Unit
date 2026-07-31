"""Gate 0.1 tests — sd_notify / watchdog heartbeat for meshsa.ui.cli.

These tests cover the testable pieces of the heartbeat instrumentation:
  * ``_send_notify`` — the sdnotify wrapper with graceful ImportError fallback.
  * ``_watchdog_loop`` — the async heartbeat coroutine.

Drop into ``packages/meshsa/tests/`` and run:
    cd packages/meshsa && pytest tests/test_cli_sdnotify.py -v

The live wiring inside ``_run`` stays ``# pragma: no cover`` per CHARTER §4.6;
these tests target the extracted helpers that ARE testable.

Target coverage: 100% on ``_send_notify`` + ``_watchdog_loop`` once the
G0.1 patch is applied to ``meshsa/ui/cli.py``.  Both helpers are marked
``xfail`` until the patch lands; they flip to xpass automatically.
"""

from __future__ import annotations

import asyncio
import sys
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Import strategy
#
# Try to import from the patched location first.  When the patch has NOT yet
# been applied, fall back to reference implementations inlined below so the
# tests still execute (and xfail correctly) rather than failing at collection
# time with an ImportError.  The fallback must NOT be imported from a path
# outside packages/meshsa/ — this file must be self-contained when dropped
# into packages/meshsa/tests/.
# ---------------------------------------------------------------------------

try:
    from meshsa.ui.cli import _send_notify, _watchdog_loop  # type: ignore[attr-defined]

    _PATCH_APPLIED = True
except (ImportError, AttributeError):
    _PATCH_APPLIED = False

if not _PATCH_APPLIED:
    # ── Reference implementations (mirrors patches/cli_sdnotify_heartbeat.py) ──
    # These run the tests against the DOCUMENTED CONTRACT before the real code
    # exists.  When the patch lands, these are dead code (the try-branch wins).

    import logging as _logging

    _ref_log = _logging.getLogger("meshsa.ui.cli._ref")

    def _send_notify(message: str) -> None:  # type: ignore[misc]  # noqa: F811
        """No-op reference implementation — graceful fallback when sdnotify absent."""
        try:
            import sdnotify  # type: ignore[import]

            notifier = sdnotify.SystemdNotifier()
            notifier.notify(message)
        except ImportError:
            _ref_log.debug(
                "sdnotify not available; systemd watchdog inactive",
                extra={"hint": "pip install sdnotify"},
            )
        except Exception as exc:
            _ref_log.warning("sd_notify failed", extra={"message": message, "error": str(exc)})

    async def _watchdog_loop(interval_s: float) -> None:  # type: ignore[misc]  # noqa: F811
        """Reference implementation — sends WATCHDOG=1 every interval_s seconds."""
        try:
            while True:
                _send_notify("WATCHDOG=1")
                await asyncio.sleep(interval_s)
        except asyncio.CancelledError:
            _send_notify("STOPPING=1")
            raise


pytestmark = pytest.mark.xfail(
    not _PATCH_APPLIED,
    reason=(
        "G0.1 sd_notify patch not yet applied to meshsa.ui.cli. "
        "Apply deliverables/meshsa-ui-validation/patches/cli_sdnotify_heartbeat.py "
        "and re-run to flip these from xfail → xpass."
    ),
    strict=True,
)


# ---------------------------------------------------------------------------
# _send_notify — sdnotify wrapper
# ---------------------------------------------------------------------------


class TestSendNotify:
    """Unit tests for the _send_notify helper (no actual systemd socket)."""

    def _sdnotify_module(self, notifier: MagicMock | None = None) -> MagicMock:
        """Construct a fake sdnotify module."""
        m = MagicMock()
        m.SystemdNotifier.return_value = notifier or MagicMock()
        return m

    def test_ready_message_delivered(self) -> None:
        """READY=1 is passed through to SystemdNotifier.notify."""
        notifier = MagicMock()
        fake_sdnotify = self._sdnotify_module(notifier)
        with patch.dict(sys.modules, {"sdnotify": fake_sdnotify}):
            _send_notify("READY=1")
        notifier.notify.assert_called_once_with("READY=1")

    def test_watchdog_message_delivered(self) -> None:
        """WATCHDOG=1 is passed through correctly."""
        notifier = MagicMock()
        fake_sdnotify = self._sdnotify_module(notifier)
        with patch.dict(sys.modules, {"sdnotify": fake_sdnotify}):
            _send_notify("WATCHDOG=1")
        notifier.notify.assert_called_once_with("WATCHDOG=1")

    def test_stopping_message_delivered(self) -> None:
        """STOPPING=1 is passed through correctly."""
        notifier = MagicMock()
        fake_sdnotify = self._sdnotify_module(notifier)
        with patch.dict(sys.modules, {"sdnotify": fake_sdnotify}):
            _send_notify("STOPPING=1")
        notifier.notify.assert_called_once_with("STOPPING=1")

    def test_missing_sdnotify_package_is_noop(self) -> None:
        """If sdnotify is not installed, _send_notify silently does nothing."""
        with patch.dict(sys.modules, {"sdnotify": None}):  # type: ignore[dict-item]
            # Must not raise — not even ImportError.
            _send_notify("READY=1")

    def test_notify_socket_error_swallowed(self) -> None:
        """A failing notify call (e.g. socket closed) must not crash the service."""
        fake_sdnotify = MagicMock()
        fake_sdnotify.SystemdNotifier.side_effect = OSError("NOTIFY_SOCKET gone")
        with patch.dict(sys.modules, {"sdnotify": fake_sdnotify}):
            # Must not raise.
            _send_notify("WATCHDOG=1")

    def test_notifier_notify_error_swallowed(self) -> None:
        """A failing notify.notify() call is swallowed, not propagated."""
        notifier = MagicMock()
        notifier.notify.side_effect = RuntimeError("pipe broken")
        fake_sdnotify = self._sdnotify_module(notifier)
        with patch.dict(sys.modules, {"sdnotify": fake_sdnotify}):
            _send_notify("WATCHDOG=1")  # must not raise

    def test_new_notifier_instance_per_call(self) -> None:
        """Each _send_notify call creates a fresh SystemdNotifier instance."""
        fake_sdnotify = self._sdnotify_module()
        with patch.dict(sys.modules, {"sdnotify": fake_sdnotify}):
            _send_notify("WATCHDOG=1")
            _send_notify("WATCHDOG=1")
        assert fake_sdnotify.SystemdNotifier.call_count == 2


# ---------------------------------------------------------------------------
# _watchdog_loop — async heartbeat coroutine
# ---------------------------------------------------------------------------


class TestWatchdogLoop:
    """Tests for the async watchdog heartbeat loop."""

    @pytest.mark.asyncio
    async def test_sends_heartbeat_before_each_sleep(self) -> None:
        """WATCHDOG=1 is sent once per iteration, before the sleep."""
        sent: list[str] = []
        call_count = 0

        async def _fake_sleep(s: float) -> None:
            nonlocal call_count
            call_count += 1
            if call_count >= 3:
                raise asyncio.CancelledError

        with (
            patch(f"{_send_notify.__module__}._send_notify", side_effect=sent.append),
            patch("asyncio.sleep", side_effect=_fake_sleep),
        ):
            try:
                await _watchdog_loop(interval_s=10.0)
            except asyncio.CancelledError:
                pass

        watchdog_beats = [m for m in sent if m == "WATCHDOG=1"]
        assert len(watchdog_beats) >= 2, "At least 2 heartbeats expected before cancellation"

    @pytest.mark.asyncio
    async def test_sends_stopping_on_cancelled_error(self) -> None:
        """STOPPING=1 is sent when the loop is cancelled (graceful shutdown)."""
        sent: list[str] = []

        with (
            patch(f"{_send_notify.__module__}._send_notify", side_effect=sent.append),
            patch("asyncio.sleep", side_effect=asyncio.CancelledError),
        ):
            try:
                await _watchdog_loop(interval_s=10.0)
            except asyncio.CancelledError:
                pass

        assert "STOPPING=1" in sent

    @pytest.mark.asyncio
    async def test_reraises_cancelled_error(self) -> None:
        """CancelledError propagates so the caller's finally block runs."""
        with (
            patch(f"{_send_notify.__module__}._send_notify"),
            patch("asyncio.sleep", side_effect=asyncio.CancelledError),
        ):
            with pytest.raises(asyncio.CancelledError):
                await _watchdog_loop(interval_s=10.0)

    @pytest.mark.asyncio
    async def test_interval_passed_to_sleep(self) -> None:
        """The configured interval is passed verbatim to asyncio.sleep."""
        sleep_calls: list[float] = []
        call_count = 0

        async def _fake_sleep(s: float) -> None:
            nonlocal call_count
            sleep_calls.append(s)
            call_count += 1
            if call_count >= 2:
                raise asyncio.CancelledError

        expected_interval = 7.5
        with (
            patch(f"{_send_notify.__module__}._send_notify"),
            patch("asyncio.sleep", side_effect=_fake_sleep),
        ):
            try:
                await _watchdog_loop(interval_s=expected_interval)
            except asyncio.CancelledError:
                pass

        assert all(
            s == expected_interval for s in sleep_calls
        ), f"asyncio.sleep must be called with {expected_interval}; got {sleep_calls}"

    @pytest.mark.asyncio
    async def test_heartbeat_before_first_sleep(self) -> None:
        """The first heartbeat is sent BEFORE the first sleep (fast-path check)."""
        order: list[str] = []
        slept = False

        async def _fake_sleep(s: float) -> None:
            nonlocal slept
            slept = True
            raise asyncio.CancelledError

        def _record_notify(msg: str) -> None:
            if not slept:
                order.append(f"notify:{msg}")
            else:
                order.append(f"after-sleep:notify:{msg}")

        with (
            patch(f"{_send_notify.__module__}._send_notify", side_effect=_record_notify),
            patch("asyncio.sleep", side_effect=_fake_sleep),
        ):
            try:
                await _watchdog_loop(interval_s=10.0)
            except asyncio.CancelledError:
                pass

        assert (
            order[0] == "notify:WATCHDOG=1"
        ), "First heartbeat must be sent before the first sleep"

    @pytest.mark.asyncio
    async def test_watchdog_interval_below_half_watchdog_sec(self) -> None:
        """Default interval (10 s) is safely below WatchdogSec (30 s) / 2 = 15 s."""
        from meshsa.ui.config import UIConfig  # type: ignore[import]

        cfg = UIConfig()
        watchdog_sec = 30  # from meshsa-ui.service WatchdogSec=30
        assert cfg.watchdog_heartbeat_s < watchdog_sec / 2, (
            f"watchdog_heartbeat_s ({cfg.watchdog_heartbeat_s}) must be < "
            f"WatchdogSec/2 ({watchdog_sec / 2}) to guarantee heartbeat delivery"
        )


# ---------------------------------------------------------------------------
# Integration: complete ready→heartbeat→stopping sequence
# ---------------------------------------------------------------------------


class TestReadyHeartbeatStoppingSequence:
    """End-to-end sequence of sd_notify messages for a single service lifetime."""

    @pytest.mark.asyncio
    async def test_full_lifecycle_message_order(self) -> None:
        """READY=1 once, then WATCHDOG=1 repeatedly, then STOPPING=1 on cancel."""
        sent: list[str] = []
        iteration = 0

        async def _fake_sleep(s: float) -> None:
            nonlocal iteration
            iteration += 1
            if iteration >= 3:
                raise asyncio.CancelledError

        # Simulate _run's READY=1 send + watchdog loop start.
        notifier = MagicMock()
        fake_sdnotify = MagicMock()
        fake_sdnotify.SystemdNotifier.return_value = notifier
        notifier.notify.side_effect = sent.append

        with (
            patch.dict(sys.modules, {"sdnotify": fake_sdnotify}),
            patch("asyncio.sleep", side_effect=_fake_sleep),
        ):
            _send_notify("READY=1")
            try:
                await _watchdog_loop(interval_s=10.0)
            except asyncio.CancelledError:
                pass

        assert sent[0] == "READY=1", "READY=1 must be the first message"
        assert "WATCHDOG=1" in sent, "WATCHDOG=1 must appear after READY=1"
        assert sent[-1] == "STOPPING=1", "STOPPING=1 must be the last message"
        # READY=1 appears exactly once.
        assert sent.count("READY=1") == 1
        # Multiple heartbeats (≥2 from loop iterations).
        assert sent.count("WATCHDOG=1") >= 2
