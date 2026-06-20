"""FPS counter math (deterministic via an injected clock)."""

from __future__ import annotations

import pytest

from jetson_yolo_gcs.core.clock import MonotonicClock, SystemClock
from jetson_yolo_gcs.utils.fps import FpsCounter
from tests.conftest import FakeClock


def test_zero_until_two_ticks() -> None:
    fps = FpsCounter(clock=FakeClock(times=[5.0]))
    assert fps.tick() == 0.0


def test_rate_over_window() -> None:
    # ticks at t=0,1,2,3 -> 3 intervals over 3s -> 1.0 fps
    fps = FpsCounter(window=10, clock=FakeClock(times=[0.0, 1.0, 2.0, 3.0]))
    fps.tick()
    fps.tick()
    fps.tick()
    assert fps.tick() == pytest.approx(1.0)


def test_zero_elapsed_returns_zero() -> None:
    fps = FpsCounter(clock=FakeClock(times=[7.0, 7.0]))
    fps.tick()
    assert fps.tick() == 0.0


def test_window_must_be_at_least_two() -> None:
    with pytest.raises(ValueError):
        FpsCounter(window=1)


def test_real_clocks_callable() -> None:
    assert isinstance(SystemClock().now(), float)
    assert isinstance(MonotonicClock().now(), float)
