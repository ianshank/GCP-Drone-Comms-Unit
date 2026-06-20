"""Full pipeline with mocked I/O: detection flows to stream + LANDING_TARGET,
and the loop's path-specific error/idle handling behaves as designed."""

from __future__ import annotations

from typing import Any

import pytest

from jetson_yolo_gcs.core.config import MavlinkSettings
from jetson_yolo_gcs.core.errors import DetectionError
from jetson_yolo_gcs.detection.base import Detection, DetectionResult
from jetson_yolo_gcs.mavlink.bridge import LandingTargetBridge
from jetson_yolo_gcs.pipeline import Pipeline
from jetson_yolo_gcs.streaming.camera import Frame
from tests.conftest import FakeCamera, FakeDetector, FakeStreamWriter


class _RecordingMav:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def landing_target_send(self, *args: object) -> None:
        self.calls.append(args)


class _RecordingConn:
    def __init__(self) -> None:
        self.mav = _RecordingMav()

    def close(self) -> None:
        pass


class _ScriptedCamera:
    """Yields a scripted sequence of frames/None, then None forever (exhausted)."""

    def __init__(self, script: list[Frame | None]) -> None:
        self._script = list(script)
        self.closed = False

    def read_frame(self) -> Frame | None:
        if self._script:
            return self._script.pop(0)
        return None

    def close(self) -> None:
        self.closed = True


def _sample() -> DetectionResult:
    return DetectionResult(
        detections=(
            Detection(class_id=0, class_name="person", confidence=0.9, bbox=(80, 80, 120, 120)),
            Detection(class_id=2, class_name="car", confidence=0.5, bbox=(0, 0, 40, 40)),
        ),
        width=200,
        height=200,
    )


def _frames(n: int) -> list[Frame]:
    return [Frame(idx=i, t=0.0, data=f"frame-{i}") for i in range(n)]


def _bridge(conn: object) -> LandingTargetBridge:
    return LandingTargetBridge(MavlinkSettings(enable_landing_target=True), connection=conn)


def test_full_step_streams_and_publishes_best() -> None:
    conn = _RecordingConn()
    camera = FakeCamera(_frames(1))
    stream = FakeStreamWriter()
    pipeline = Pipeline(
        camera=camera,
        detector=FakeDetector(_sample()),
        stream=stream,
        bridge=_bridge(conn),
    )
    assert pipeline.step() is True
    assert stream.frames == ["frame-0"]
    assert len(conn.mav.calls) == 1
    # No more frames -> step returns False.
    assert pipeline.step() is False


def test_run_processes_all_frames_then_stops() -> None:
    camera = FakeCamera(_frames(3))
    detector = FakeDetector(_sample())
    pipeline = Pipeline(camera=camera, detector=detector)
    # max_consecutive_empty=1 stops at the first empty (end of the finite fake source).
    assert pipeline.run(max_consecutive_empty=1) == 3
    assert detector.calls == 3
    assert pipeline.fps >= 0.0


def test_run_tolerates_transient_empty_then_resumes() -> None:
    # frame, transient None, frame, then exhausted.
    cam = _ScriptedCamera([_frames(1)[0], None, Frame(idx=1, t=0.0, data="f1")])
    slept: list[float] = []
    pipeline = Pipeline(camera=cam, detector=FakeDetector(_sample()))
    processed = pipeline.run(max_consecutive_empty=2, sleep=slept.append)
    assert processed == 2  # both real frames processed despite the gap
    assert slept  # idle back-off was exercised on the transient empty


def test_request_stop_ends_run() -> None:
    pipeline = Pipeline(camera=FakeCamera(_frames(5)), detector=FakeDetector(_sample()))
    pipeline.request_stop()
    assert pipeline.run(sleep=lambda _s: None) == 0


def test_step_drops_detection_error_and_skips_publish() -> None:
    class _RaisingDetector:
        def detect(self, frame: Any) -> DetectionResult:
            raise DetectionError("malformed output")

        def close(self) -> None:
            pass

    conn = _RecordingConn()
    pipeline = Pipeline(
        camera=FakeCamera(_frames(1)),
        detector=_RaisingDetector(),
        bridge=_bridge(conn),
    )
    assert pipeline.step() is True  # loop survives
    assert pipeline.dropped_detections == 1
    assert conn.mav.calls == []  # never reached the publish path


def test_step_propagates_unexpected_detector_error() -> None:
    class _BoomDetector:
        def detect(self, frame: Any) -> DetectionResult:
            raise RuntimeError("cuda oom")

        def close(self) -> None:
            pass

    pipeline = Pipeline(camera=FakeCamera(_frames(1)), detector=_BoomDetector())
    with pytest.raises(RuntimeError):
        pipeline.step()


def test_step_drops_stream_error_best_effort() -> None:
    class _RaisingStream:
        def write(self, frame: Any) -> None:
            raise OSError("egress broke")

        def close(self) -> None:
            pass

    pipeline = Pipeline(
        camera=FakeCamera(_frames(1)),
        detector=FakeDetector(_sample()),
        stream=_RaisingStream(),
    )
    assert pipeline.step() is True
    assert pipeline.dropped_stream == 1


def test_step_propagates_publish_error_loudly() -> None:
    class _RaisingMav:
        def landing_target_send(self, *args: object) -> None:
            raise RuntimeError("link down")

    class _Conn:
        def __init__(self) -> None:
            self.mav = _RaisingMav()

        def close(self) -> None:
            pass

    pipeline = Pipeline(
        camera=FakeCamera(_frames(1)),
        detector=FakeDetector(_sample()),
        bridge=_bridge(_Conn()),
    )
    with pytest.raises(RuntimeError):
        pipeline.step()


def test_no_target_match_skips_publish() -> None:
    conn = _RecordingConn()
    pipeline = Pipeline(
        camera=FakeCamera(_frames(1)),
        detector=FakeDetector(_sample()),
        bridge=_bridge(conn),
        target_classes=frozenset({"boat"}),  # no detection matches
    )
    assert pipeline.step() is True
    assert conn.mav.calls == []


def test_target_class_filter_selects_named_class() -> None:
    captured: list[Detection] = []

    class _CapturingBridge(LandingTargetBridge):
        def publish(self, detection: Detection, result: DetectionResult) -> None:
            captured.append(detection)

    bridge = _CapturingBridge(
        MavlinkSettings(enable_landing_target=True), connection=_RecordingConn()
    )
    pipeline = Pipeline(
        camera=FakeCamera(_frames(1)),
        detector=FakeDetector(_sample()),
        bridge=bridge,
        target_classes=frozenset({"car"}),
    )
    pipeline.step()
    assert len(captured) == 1
    assert captured[0].class_name == "car"  # not the higher-confidence "person"


def test_close_releases_resources() -> None:
    camera = FakeCamera(_frames(0))
    stream = FakeStreamWriter()
    pipeline = Pipeline(camera=camera, detector=FakeDetector(_sample()), stream=stream)
    pipeline.close()
    assert camera.closed is True
    assert stream.closed is True


def test_close_swallows_raising_closer() -> None:
    class _RaisingCamera:
        def read_frame(self) -> Frame | None:
            return None

        def close(self) -> None:
            raise OSError("device busy")

    pipeline = Pipeline(camera=_RaisingCamera(), detector=FakeDetector(_sample()))
    pipeline.close()  # must not raise
