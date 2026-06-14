"""CaptureWriter: frame-index logging, overflow policy, timestamp sync, shutdown.

Mirrors ``tests/test_fpv_logger.py``: hand fakes (no mock, no hardware), a
``ManualClock`` shared with the logger, a ``tmp_path`` dataset dir, and
assertions on JSONL records + drop counters. The injected ``encode`` keeps the
real muxer out of the test path entirely.
"""

from __future__ import annotations

import json
import os
import threading
import time

from _fpv_helpers import ManualClock

from meshsa.fpv.camera import CaptureWriter, Frame
from meshsa.fpv.config import CameraSettings, LoggerSettings
from meshsa.fpv.crsf.telemetry import LinkStatistics
from meshsa.fpv.flight_logger import FlightLogger


class FakeCamera:
    """Yields ``frames`` one per ``read_frame`` call, then ``None`` forever."""

    def __init__(self, frames: list[Frame]) -> None:
        self._frames = list(frames)
        self._i = 0
        self.closed = False

    def read_frame(self) -> Frame | None:
        if self._i < len(self._frames):
            frame = self._frames[self._i]
            self._i += 1
            return frame
        return None

    def close(self) -> None:
        self.closed = True


def _ls() -> LinkStatistics:
    return LinkStatistics(-60, -60, 100, 8, 0, 0, 100, -60, 100, 8)


def _logger(tmp_path, clock) -> FlightLogger:
    return FlightLogger(
        LoggerSettings(sessions_root=str(tmp_path)),
        clock=clock,
        git_sha="deadbeef",
        now_utc="2026-06-12T00:00:00+00:00",
        session_id="camsess",
    )


def _read_lines(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _wait_until(predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)


def test_capture_writes_frame_index_records(tmp_path):
    clock = ManualClock()
    logger = _logger(tmp_path, clock)
    logger.start()
    encoded: list[object] = []
    frames = [Frame(idx=i, t=0.0, data=f"buf{i}") for i in range(3)]
    writer = CaptureWriter(
        CameraSettings(), FakeCamera(frames), logger, encode=encoded.append, clock=clock
    )
    writer.start()
    _wait_until(lambda: len(encoded) == 3)
    writer.close()
    logger.close()

    recs = _read_lines(os.path.join(logger.session_dir, "frames.jsonl"))[1:]
    assert [r["frame_idx"] for r in recs] == [0, 1, 2]
    assert all(isinstance(r["t"], float) for r in recs)
    assert encoded == ["buf0", "buf1", "buf2"]


def test_capture_drops_and_counts_on_overflow(tmp_path):
    clock = ManualClock()
    logger = _logger(tmp_path, clock)
    logger.start()
    release = threading.Event()

    def blocking_encode(_buffer: object) -> None:
        release.wait(timeout=2.0)  # hold the single in-flight slot so the queue fills

    frames = [Frame(idx=i, t=0.0, data=f"buf{i}") for i in range(5)]
    writer = CaptureWriter(
        CameraSettings(capture_queue_len=1),
        FakeCamera(frames),
        logger,
        encode=blocking_encode,
        clock=clock,
    )
    writer.start()
    # All frame indices are recorded regardless of encode backpressure; the
    # overflow only drops the buffer destined for the (stalled) encoder.
    _wait_until(lambda: writer.dropped_frames >= 1)
    assert writer.dropped_frames >= 1
    release.set()
    writer.close()
    logger.close()


def test_timestamp_sync_with_telemetry(tmp_path):
    # Frame timestamps share the logger's clock, so a frame captured between two
    # telemetry samples lands strictly between their timestamps.
    clock = ManualClock()
    logger = _logger(tmp_path, clock)
    logger.start()
    encoded = threading.Event()
    frames = [Frame(idx=0, t=0.0, data="buf")]

    def encode(_buffer: object) -> None:
        encoded.set()

    writer = CaptureWriter(CameraSettings(), FakeCamera(frames), logger, encode=encode, clock=clock)

    clock.t = 10.0
    logger.record_telemetry(_ls())  # before the frame
    clock.t = 11.0
    writer.start()
    _wait_until(encoded.is_set)
    clock.t = 12.0
    logger.record_telemetry(_ls())  # after the frame
    writer.close()
    logger.close()

    tel = _read_lines(os.path.join(logger.session_dir, "telemetry.jsonl"))[1:]
    frame = _read_lines(os.path.join(logger.session_dir, "frames.jsonl"))[1]
    assert tel[0]["t"] < frame["t"] < tel[1]["t"]
    assert frame["t"] == 11.0


def test_clean_shutdown(tmp_path):
    clock = ManualClock()
    logger = _logger(tmp_path, clock)
    logger.start()
    cam = FakeCamera([Frame(idx=0, t=0.0, data="buf")])
    writer = CaptureWriter(CameraSettings(), cam, logger, encode=lambda _b: None, clock=clock)
    writer.start()
    writer.close()
    writer.close()  # idempotent
    assert cam.closed is True
    logger.close()


def test_close_before_start_is_noop(tmp_path):
    clock = ManualClock()
    logger = _logger(tmp_path, clock)
    cam = FakeCamera([])
    writer = CaptureWriter(CameraSettings(), cam, logger, encode=lambda _b: None, clock=clock)
    writer.close()  # never started -> no-op, source not touched
    assert cam.closed is False


def test_default_clock_used_when_none_injected(tmp_path):
    clock = ManualClock()
    logger = _logger(tmp_path, clock)
    logger.start()
    encoded = threading.Event()
    cam = FakeCamera([Frame(idx=0, t=0.0, data="buf")])
    # No clock injected -> the writer stamps with a real MonotonicClock float.
    with CaptureWriter(CameraSettings(), cam, logger, encode=lambda _b: encoded.set()) as writer:
        _wait_until(encoded.is_set)
        assert writer.dropped_frames == 0
    logger.close()
    frame = _read_lines(os.path.join(logger.session_dir, "frames.jsonl"))[1]
    assert isinstance(frame["t"], float)


def test_encode_failure_does_not_kill_thread(tmp_path):
    # A frame whose encode raises is logged-and-dropped; a later frame still encodes.
    clock = ManualClock()
    logger = _logger(tmp_path, clock)
    logger.start()
    seen: list[object] = []

    def encode(buffer: object) -> None:
        if buffer == "boom":
            raise ValueError("bad frame")
        seen.append(buffer)

    frames = [Frame(idx=0, t=0.0, data="boom"), Frame(idx=1, t=0.0, data="ok")]
    writer = CaptureWriter(CameraSettings(), FakeCamera(frames), logger, encode=encode, clock=clock)
    writer.start()
    _wait_until(lambda: seen == ["ok"])
    writer.close()
    logger.close()
    assert seen == ["ok"]
    # Both frame indices were still recorded even though one encode raised.
    recs = _read_lines(os.path.join(logger.session_dir, "frames.jsonl"))[1:]
    assert [r["frame_idx"] for r in recs] == [0, 1]
