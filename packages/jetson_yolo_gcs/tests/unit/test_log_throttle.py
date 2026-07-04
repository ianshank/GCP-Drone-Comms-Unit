"""Shared rate-limited-logging predicate boundaries."""

from __future__ import annotations

import pytest

from jetson_yolo_gcs.utils.log_throttle import should_log_throttled


@pytest.mark.parametrize(
    ("count", "every", "expected"),
    [
        (1, 100, True),  # always log the first
        (2, 100, False),
        (99, 100, False),
        (100, 100, True),  # and every Nth thereafter
        (101, 100, False),
        (200, 100, True),
        (1, 1, True),  # every==1 -> log every time
        (5, 1, True),
    ],
)
def test_should_log_throttled(count: int, every: int, expected: bool) -> None:
    assert should_log_throttled(count, every) is expected
