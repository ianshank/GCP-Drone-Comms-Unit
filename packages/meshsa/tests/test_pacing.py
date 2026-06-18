"""Pacer token-bucket timing (meshsa.transports.pacing).

A manually-advanced clock + a recording sleep make the delay schedule fully
deterministic with no real waiting.
"""

from __future__ import annotations

import pytest

from meshsa.transports.pacing import Pacer


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def now(self) -> float:
        return self.t


def _recording_sleep(clock: _Clock, log: list[float]):
    async def sleep(secs: float) -> None:
        log.append(secs)
        clock.t += secs  # sleeping advances the (fake) clock

    return sleep


async def test_burst_one_paces_every_send_after_the_first():
    clock = _Clock()
    slept: list[float] = []
    pacer = Pacer(rate_hz=10.0, burst=1, clock=clock, sleep=_recording_sleep(clock, slept))
    await pacer.acquire()  # initial token -> no wait
    assert slept == []
    await pacer.acquire()  # bucket empty -> wait one interval (0.1 s)
    assert slept == [pytest.approx(0.1)]
    await pacer.acquire()  # still capped at the steady rate
    assert slept == [pytest.approx(0.1), pytest.approx(0.1)]


async def test_burst_allows_n_immediate_then_paces():
    clock = _Clock()
    slept: list[float] = []
    pacer = Pacer(rate_hz=20.0, burst=3, clock=clock, sleep=_recording_sleep(clock, slept))
    for _ in range(3):  # a burst of 3 sends does not wait
        await pacer.acquire()
    assert slept == []
    await pacer.acquire()  # 4th exceeds the burst -> wait 1/20 s
    assert slept == [pytest.approx(0.05)]


async def test_idle_time_refills_tokens():
    clock = _Clock()
    slept: list[float] = []
    pacer = Pacer(rate_hz=10.0, burst=1, clock=clock, sleep=_recording_sleep(clock, slept))
    await pacer.acquire()  # consume the token
    clock.t += 0.1  # a full interval passes -> one token refills
    await pacer.acquire()  # no wait needed
    assert slept == []


async def test_partial_token_refill_waits_only_the_remaining_fraction():
    # burst=2, drain both, then advance half an interval: 0.5 token accrues, so the
    # next acquire waits only the remaining 0.5*interval. Exercises the subtlest
    # (fractional) regime of the bucket where a partial token has refilled.
    clock = _Clock()
    slept: list[float] = []
    pacer = Pacer(rate_hz=10.0, burst=2, clock=clock, sleep=_recording_sleep(clock, slept))
    await pacer.acquire()  # 2 -> 1
    await pacer.acquire()  # 1 -> 0
    assert slept == []
    clock.t += 0.05  # half of the 0.1 s interval -> 0.5 token refills
    await pacer.acquire()  # need 1, have 0.5 -> wait the remaining 0.05 s
    assert slept == [pytest.approx(0.05)]


def test_invalid_params_raise():
    with pytest.raises(ValueError, match="rate_hz"):
        Pacer(rate_hz=0.0)
    with pytest.raises(ValueError, match="burst"):
        Pacer(rate_hz=1.0, burst=0)


def test_default_clock_is_monotonic():
    # Pacing measures elapsed time, so the default timebase must be monotonic.
    from meshsa.protocols import MonotonicClock

    assert isinstance(Pacer(rate_hz=1.0)._clock, MonotonicClock)


async def test_backward_clock_does_not_oversleep():
    # A clock that jumps backward must clamp elapsed to 0: no negative refill and
    # no huge spurious sleep — just the normal one-interval wait.
    clock = _Clock()
    slept: list[float] = []
    pacer = Pacer(rate_hz=10.0, burst=1, clock=clock, sleep=_recording_sleep(clock, slept))
    await pacer.acquire()  # consume the token (last = 0)
    clock.t = -5.0  # clock steps backward
    await pacer.acquire()  # clamped -> wait exactly one interval (0.1 s), not 5+ s
    assert slept == [pytest.approx(0.1)]
