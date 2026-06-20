"""Full pipeline with mocked I/O: detection flows to stream + LANDING_TARGET."""

from __future__ import annotations

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


def test_full_step_streams_and_publishes_best() -> None:
    from jetson_yolo_gcs.core.config import MavlinkSettings

    conn = _RecordingConn()
    bridge = LandingTargetBridge(MavlinkSettings(enable_landing_target=True), connection=conn)
    camera = FakeCamera(_frames(1))
    stream = FakeStreamWriter()
    pipeline = Pipeline(
        camera=camera,
        detector=FakeDetector(_sample()),
        stream=stream,
        bridge=bridge,
    )
    assert pipeline.step() is True
    # Frame was streamed and a LANDING_TARGET was published for the best detection.
    assert stream.frames == ["frame-0"]
    assert len(conn.mav.calls) == 1
    # No more frames -> step returns False.
    assert pipeline.step() is False


def test_run_processes_all_frames_then_stops() -> None:
    camera = FakeCamera(_frames(3))
    detector = FakeDetector(_sample())
    pipeline = Pipeline(camera=camera, detector=detector)
    assert pipeline.run() == 3
    assert detector.calls == 3
    assert pipeline.fps >= 0.0


def test_target_class_filter_selects_named_class() -> None:
    from jetson_yolo_gcs.core.config import MavlinkSettings

    captured: list[Detection] = []

    class _Bridge(LandingTargetBridge):
        def publish(self, detection: Detection, result: DetectionResult) -> None:
            captured.append(detection)

    bridge = _Bridge(MavlinkSettings(enable_landing_target=True), connection=_RecordingConn())
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
