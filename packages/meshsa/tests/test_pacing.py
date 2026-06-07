import pytest

from meshsa.pacing import Pacer


class ManualClock:
    """A settable, non-advancing clock (the conftest FakeClock auto-increments,
    which can't model controlled time for pacing assertions)."""

    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def now(self) -> float:
        return self.t


class RecordSleep:
    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, secs: float) -> None:
        self.calls.append(secs)


async def test_pacer_first_wait_does_not_sleep():
    sleep = RecordSleep()
    p = Pacer(min_interval_s=0.2, clock=ManualClock(100.0), sleep=sleep)
    await p.wait()
    assert sleep.calls == []


async def test_pacer_holds_full_interval_when_no_time_passed():
    clock = ManualClock(100.0)
    sleep = RecordSleep()
    p = Pacer(min_interval_s=0.2, clock=clock, sleep=sleep)
    await p.wait()  # stamp last = 100.0
    await p.wait()  # clock unchanged -> full hold
    assert sleep.calls == [pytest.approx(0.2)]


async def test_pacer_requests_only_residual_delay():
    clock = ManualClock(100.0)
    sleep = RecordSleep()
    p = Pacer(min_interval_s=0.2, clock=clock, sleep=sleep)
    await p.wait()
    clock.t = 100.05  # 0.05 already elapsed -> 0.15 residual
    await p.wait()
    assert sleep.calls == [pytest.approx(0.15)]


async def test_pacer_no_sleep_when_interval_already_elapsed():
    clock = ManualClock(100.0)
    sleep = RecordSleep()
    p = Pacer(min_interval_s=0.2, clock=clock, sleep=sleep)
    await p.wait()
    clock.t = 100.5  # past the interval
    await p.wait()
    assert sleep.calls == []


async def test_pacer_stamps_reference_from_post_sleep_clock():
    # After sleeping, the reference is re-read from the clock (which advanced during
    # the sleep) so spacing does not collapse on the next call.
    clock = ManualClock(100.0)

    async def sleep(secs: float) -> None:
        clock.t += secs  # simulate real time passing during the await

    p = Pacer(min_interval_s=0.2, clock=clock, sleep=sleep)
    await p.wait()  # last = 100.0
    await p.wait()  # holds 0.2 -> clock 100.2, last 100.2
    await p.wait()  # holds 0.2 again -> clock 100.4
    assert clock.t == pytest.approx(100.4)
