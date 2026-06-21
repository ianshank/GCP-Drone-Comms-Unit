"""Tests for the exponential backoff schedule in meshsa.transports.backoff.

Uses an injectable fake sleep to record actual delay values, verifying the
initial → factor growth → cap at maximum → reset sequence without real waiting.
"""

from __future__ import annotations

import pytest

from meshsa.transports.backoff import Backoff

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_recorder() -> tuple[list[float], Backoff]:
    """Return (recorded_delays, backoff) with a fake sleep that captures delays."""
    recorded: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        recorded.append(seconds)

    bo = Backoff(initial_s=1.0, max_s=10.0, factor=2.0, sleep=_fake_sleep)
    return recorded, bo


# ---------------------------------------------------------------------------
# Core behaviour
# ---------------------------------------------------------------------------


class TestBackoffInitial:
    """Starting state of a freshly-constructed Backoff."""

    def test_initial_current(self) -> None:
        """Current delay starts at the initial value."""
        _, bo = _make_recorder()
        assert bo.current == 1.0

    @pytest.mark.parametrize("initial", [0.5, 2.0, 5.0])
    def test_initial_parametrized(self, initial: float) -> None:
        """current equals initial_s for various starting values."""
        bo = Backoff(initial_s=initial, max_s=60.0, factor=2.0)
        assert bo.current == initial


class TestBackoffGrowth:
    """sleep_and_advance multiplies current by factor each call."""

    async def test_single_advance(self) -> None:
        """After one call, delay doubles (factor=2)."""
        recorded, bo = _make_recorder()
        await bo.sleep_and_advance()
        assert recorded == [1.0]
        assert bo.current == 2.0

    async def test_double_advance(self) -> None:
        """After two calls, delay is initial * factor^2."""
        recorded, bo = _make_recorder()
        await bo.sleep_and_advance()
        await bo.sleep_and_advance()
        assert recorded == [1.0, 2.0]
        assert bo.current == 4.0

    async def test_triple_advance(self) -> None:
        """After three calls, delay is initial * factor^3."""
        recorded, bo = _make_recorder()
        await bo.sleep_and_advance()
        await bo.sleep_and_advance()
        await bo.sleep_and_advance()
        assert recorded == [1.0, 2.0, 4.0]
        assert bo.current == 8.0


class TestBackoffCap:
    """Delay never exceeds maximum."""

    async def test_caps_at_maximum(self) -> None:
        """Growth stops at max_s even after many advances."""
        recorded, bo = _make_recorder()  # initial=1, max=10, factor=2
        # 1 → 2 → 4 → 8 → 10(cap) → 10 → 10
        for _ in range(7):
            await bo.sleep_and_advance()
        assert recorded == [1.0, 2.0, 4.0, 8.0, 10.0, 10.0, 10.0]
        assert bo.current == 10.0

    async def test_cap_with_custom_max(self) -> None:
        """Cap works with a different maximum value."""
        recorded: list[float] = []

        async def _fake(s: float) -> None:
            recorded.append(s)

        bo = Backoff(initial_s=3.0, max_s=7.0, factor=2.0, sleep=_fake)
        await bo.sleep_and_advance()  # sleeps 3, grows to 6
        await bo.sleep_and_advance()  # sleeps 6, grows to 7 (capped from 12)
        await bo.sleep_and_advance()  # sleeps 7, stays at 7
        assert recorded == [3.0, 6.0, 7.0]
        assert bo.current == 7.0


class TestBackoffReset:
    """reset() returns current to initial."""

    async def test_reset_after_advances(self) -> None:
        """After several advances, reset restores the initial delay."""
        recorded, bo = _make_recorder()
        await bo.sleep_and_advance()
        await bo.sleep_and_advance()
        assert bo.current == 4.0

        bo.reset()
        assert bo.current == 1.0

        # Next sleep should use the reset value.
        await bo.sleep_and_advance()
        assert recorded[-1] == 1.0
        assert bo.current == 2.0

    def test_reset_without_advance(self) -> None:
        """Reset on a fresh backoff is a no-op (stays at initial)."""
        _, bo = _make_recorder()
        bo.reset()
        assert bo.current == 1.0

    async def test_reset_at_cap(self) -> None:
        """Reset after hitting the cap returns to initial, not max."""
        recorded, bo = _make_recorder()
        for _ in range(6):
            await bo.sleep_and_advance()
        assert bo.current == 10.0

        bo.reset()
        assert bo.current == 1.0


class TestBackoffInjectableSleep:
    """The sleep callable is injectable and records actual delay values."""

    async def test_recorded_delays_match_current(self) -> None:
        """Each recorded delay matches the current value before that step."""
        recorded, bo = _make_recorder()
        expected_sleeps = [1.0, 2.0, 4.0, 8.0, 10.0]
        for _ in range(5):
            await bo.sleep_and_advance()
        assert recorded == expected_sleeps

    async def test_default_sleep_is_asyncio(self) -> None:
        """When no sleep is injected, Backoff uses asyncio.sleep (no crash)."""

        bo = Backoff(initial_s=0.0, max_s=0.0, factor=2.0)
        # With initial=0 and max=0, this should complete instantly.
        await bo.sleep_and_advance()
        assert bo.current == 0.0


class TestBackoffFullSequence:
    """End-to-end sequence: grow → cap → reset → grow again."""

    async def test_full_lifecycle(self) -> None:
        """Verify the complete lifecycle: initial → growth → cap → reset → re-grow."""
        recorded: list[float] = []

        async def _fake(s: float) -> None:
            recorded.append(s)

        bo = Backoff(initial_s=2.0, max_s=10.0, factor=3.0, sleep=_fake)

        # Phase 1: grow to cap
        await bo.sleep_and_advance()  # sleep 2, current → 6
        await bo.sleep_and_advance()  # sleep 6, current → 10 (capped from 18)
        await bo.sleep_and_advance()  # sleep 10, current → 10 (stays capped)
        assert recorded == [2.0, 6.0, 10.0]
        assert bo.current == 10.0

        # Phase 2: reset simulating successful reconnect
        bo.reset()
        assert bo.current == 2.0

        # Phase 3: re-grow from initial
        await bo.sleep_and_advance()  # sleep 2, current → 6
        assert recorded == [2.0, 6.0, 10.0, 2.0]
        assert bo.current == 6.0
