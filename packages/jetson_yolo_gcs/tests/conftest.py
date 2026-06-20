"""Shared test fakes (mirrors meshsa's fakes-first, hardware-free convention)."""

from __future__ import annotations

from typing import Any

import pytest

from jetson_yolo_gcs.detection.base import Detection, DetectionResult
from jetson_yolo_gcs.streaming.camera import Frame


class FakeClock:
    """Deterministic clock: returns preset times or increments by 1.0 each call."""

    def __init__(self, times: list[float] | None = None) -> None:
        self._times = list(times) if times else None
        self._t = 0.0

    def now(self) -> float:
        if self._times is not None:
            return self._times.pop(0)
        self._t += 1.0
        return self._t


class FakeCamera:
    """Yields a fixed list of frames then ``None`` (end of stream)."""

    def __init__(self, frames: list[Frame]) -> None:
        self._frames = list(frames)
        self.closed = False

    def read_frame(self) -> Frame | None:
        if self._frames:
            return self._frames.pop(0)
        return None

    def close(self) -> None:
        self.closed = True


class FakeDetector:
    """Returns a preset :class:`DetectionResult` for every frame."""

    def __init__(self, result: DetectionResult) -> None:
        self._result = result
        self.calls = 0
        self.closed = False

    def detect(self, frame: Any) -> DetectionResult:
        self.calls += 1
        return self._result

    def close(self) -> None:
        self.closed = True


class FakeStreamWriter:
    """Records every frame written and whether it was closed."""

    def __init__(self) -> None:
        self.frames: list[Any] = []
        self.closed = False

    def write(self, frame: Any) -> None:
        self.frames.append(frame)

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def fake_clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def sample_result() -> DetectionResult:
    return DetectionResult(
        detections=(
            Detection(class_id=0, class_name="person", confidence=0.9, bbox=(10, 20, 110, 220)),
            Detection(class_id=2, class_name="car", confidence=0.5, bbox=(0, 0, 50, 50)),
        ),
        width=200,
        height=200,
    )
