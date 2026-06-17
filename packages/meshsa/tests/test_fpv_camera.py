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
    raise AssertionError(f"timed out waiting for {predicate!r} after {timeout}s")


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


def test_idle_poll_backs_off_when_read_returns_none(tmp_path):
    # A source that returns None (disconnected) then a frame must recover without
    # spinning: the loop sleeps the configured idle_poll_s on each None instead of
    # busy-looping at 100% CPU. We inject the sleep and assert it is called.
    clock = ManualClock()
    logger = _logger(tmp_path, clock)
    logger.start()
    encoded = threading.Event()
    sleeps: list[float] = []

    class FlakyCamera:
        """Returns None first (disconnected), then one real frame, then None."""

        def __init__(self) -> None:
            self._calls = 0
            self.closed = False

        def read_frame(self) -> Frame | None:
            self._calls += 1
            if self._calls == 1:
                return None
            if self._calls == 2:
                return Frame(idx=0, t=0.0, data="buf")
            return None

        def close(self) -> None:
            self.closed = True

    settings = CameraSettings(idle_poll_s=0.25)
    writer = CaptureWriter(
        settings,
        FlakyCamera(),
        logger,
        encode=lambda _b: encoded.set(),
        clock=clock,
        sleep=sleeps.append,
    )
    writer.start()
    _wait_until(encoded.is_set)
    writer.close()
    logger.close()

    # Recovered (frame encoded) AND backed off with the configured interval, not
    # a hardcoded value, on the None reads -> no busy-loop.
    assert sleeps  # at least one idle back-off happened
    assert all(dt == settings.idle_poll_s for dt in sleeps)


def test_record_frame_failure_does_not_kill_thread(tmp_path, monkeypatch):
    # If record_frame raises once, the capture thread must keep running and log the
    # next frame — a single bad iteration cannot silently stop all capture.
    clock = ManualClock()
    logger = _logger(tmp_path, clock)
    logger.start()
    encoded: list[object] = []
    calls = {"n": 0}
    real_record = logger.record_frame

    def flaky_record(frame_idx: int, t: float | None = None) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient record failure")
        real_record(frame_idx, t)

    monkeypatch.setattr(logger, "record_frame", flaky_record)
    frames = [Frame(idx=0, t=0.0, data="lost"), Frame(idx=1, t=0.0, data="ok")]
    writer = CaptureWriter(
        CameraSettings(idle_poll_s=0.0),
        FakeCamera(frames),
        logger,
        encode=encoded.append,
        clock=clock,
    )
    writer.start()
    _wait_until(lambda: encoded == ["ok"])
    writer.close()
    logger.close()
    # The first frame's record raised (lost), but the thread survived and the
    # second frame was recorded + encoded.
    assert encoded == ["ok"]
    recs = _read_lines(os.path.join(logger.session_dir, "frames.jsonl"))[1:]
    assert [r["frame_idx"] for r in recs] == [1]


def test_close_releases_source_before_joining_capture(tmp_path):
    # close() must close the source BEFORE joining the capture thread so a backend
    # blocked in read_frame is unblocked and the join cannot time out. The fake's
    # read_frame blocks until close() fires; with the source closed first the
    # capture thread unblocks and the join completes well within the timeout, so
    # the thread is dead afterwards (a wrong order would time out, leaving it
    # alive). The recorded order proves source.close ran before the join returned.
    clock = ManualClock()
    logger = _logger(tmp_path, clock)
    logger.start()
    order: list[str] = []
    unblock = threading.Event()
    read_entered = threading.Event()

    class BlockingCamera:
        """read_frame blocks until close() is called (simulates a wedged backend)."""

        def read_frame(self) -> Frame | None:
            read_entered.set()
            unblock.wait(timeout=2.0)
            return None

        def close(self) -> None:
            order.append("source.close")
            unblock.set()  # unblock the in-flight read_frame

    writer = CaptureWriter(
        CameraSettings(capture_shutdown_timeout_s=2.0, idle_poll_s=0.0),
        BlockingCamera(),
        logger,
        encode=lambda _b: None,
        clock=clock,
    )
    writer.start()
    # Ensure the capture thread is genuinely blocked inside read_frame.
    _wait_until(read_entered.is_set)
    writer.close()
    order.append("close.returned")
    logger.close()
    # Source was closed (unblocking read_frame) before close() returned, and the
    # capture thread terminated within the timeout (proof the join did not block).
    assert order == ["source.close", "close.returned"]
    assert writer._capture_thread is not None
    assert not writer._capture_thread.is_alive()


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
