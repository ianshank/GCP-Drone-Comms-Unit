"""Pipeline ↔ tracker integration: read-only track counters, fault passthrough, and a pin
that the tracker never changes LANDING_TARGET target selection."""

from __future__ import annotations

from jetson_yolo_gcs.core.config import MavlinkSettings
from jetson_yolo_gcs.detection.base import Detection, DetectionResult
from jetson_yolo_gcs.mavlink.bridge import LandingTargetBridge
from jetson_yolo_gcs.pipeline import Pipeline
from jetson_yolo_gcs.streaming.camera import Frame
from jetson_yolo_gcs.tracking.base import TrackedDetection, TrackerBase
from tests.conftest import FakeCamera, FakeDetector


def _multi() -> DetectionResult:
    return DetectionResult(
        detections=(
            Detection(class_id=0, class_name="person", confidence=0.9, bbox=(80, 80, 120, 120)),
            Detection(class_id=2, class_name="car", confidence=0.5, bbox=(0, 0, 40, 40)),
        ),
        width=200,
        height=200,
    )


def _frames(n: int) -> list[Frame]:
    return [Frame(idx=i, t=0.0, data=f"f{i}") for i in range(n)]


class _ScriptedTracker(TrackerBase):
    """Returns a preset tuple of :class:`TrackedDetection` per ``update`` call."""

    def __init__(self, script: list[tuple[TrackedDetection, ...]]) -> None:
        self._script = list(script)
        self.calls = 0
        self.closed = False

    def update(self, result: DetectionResult) -> tuple[TrackedDetection, ...]:
        self.calls += 1
        return self._script.pop(0)

    def close(self) -> None:
        self.closed = True


class _RaisingTracker(TrackerBase):
    def update(self, result: DetectionResult) -> tuple[TrackedDetection, ...]:
        raise RuntimeError("norfair boom")


class _Conn:
    class _Mav:
        def landing_target_send(self, *args: object) -> None:
            pass

    def __init__(self) -> None:
        self.mav = _Conn._Mav()

    def recv_match(self, *, type: str, blocking: bool) -> object | None:  # noqa: A002
        return None

    def close(self) -> None:
        pass


class _CapturingBridge(LandingTargetBridge):
    """Records which detection selection chose to publish; gate forced open."""

    def __init__(self) -> None:
        super().__init__(
            MavlinkSettings(enable_landing_target=True, require_heartbeat=False),
            connection=_Conn(),
        )
        self.captured: list[Detection] = []

    def publish(
        self, detection: Detection, result: DetectionResult, *, capture_t: float | None = None
    ) -> bool:
        self.captured.append(detection)
        return True

    def poll_heartbeat(self) -> bool:
        return True


def test_track_counters_update_across_frames() -> None:
    det = _multi().detections[0]
    tracker = _ScriptedTracker(
        [
            (TrackedDetection(det, 1),),  # one track
            (TrackedDetection(det, 1),),  # same object, same id
            (TrackedDetection(det, 1), TrackedDetection(det, 2)),  # a second track appears
        ]
    )
    pipeline = Pipeline(
        camera=FakeCamera(_frames(3)), detector=FakeDetector(_multi()), tracker=tracker
    )
    for _ in range(3):
        assert pipeline.step() is True
    assert tracker.calls == 3
    assert pipeline.tracks_active == 2  # last frame had two live tracks
    assert pipeline.tracks_total == 2  # distinct ids seen: {1, 2}
    snap = pipeline.snapshot()
    assert snap["tracks_active"] == 2
    assert snap["tracks_total"] == 2
    assert snap["dropped_tracks"] == 0


def test_tracker_fault_dropped_and_counted_not_fatal() -> None:
    pipeline = Pipeline(
        camera=FakeCamera(_frames(2)), detector=FakeDetector(_multi()), tracker=_RaisingTracker()
    )
    assert pipeline.step() is True  # loop survives the tracker fault (1st drop logs)
    assert pipeline.step() is True  # 2nd drop exercises the no-relog throttle branch
    assert pipeline.dropped_tracks == 2
    assert pipeline.tracks_active == 0
    assert pipeline.snapshot()["dropped_tracks"] == 2


def test_tracker_does_not_change_published_target() -> None:
    # The tracker "confirms" the low-confidence car, but selection must still publish the
    # highest-confidence person — identical with the tracker on vs off.
    def published_class(*, with_tracker: bool) -> list[str]:
        bridge = _CapturingBridge()
        result = _multi()
        tracker = (
            _ScriptedTracker([(TrackedDetection(result.detections[1], 1),)])
            if with_tracker
            else None
        )
        pipeline = Pipeline(
            camera=FakeCamera(_frames(1)),
            detector=FakeDetector(result),
            bridge=bridge,
            tracker=tracker,
        )
        assert pipeline.step() is True
        return [d.class_name for d in bridge.captured]

    assert published_class(with_tracker=False) == ["person"]
    assert published_class(with_tracker=True) == ["person"]


def test_snapshot_track_counters_default_zero_without_tracker() -> None:
    pipeline = Pipeline(camera=FakeCamera(_frames(0)), detector=FakeDetector(_multi()))
    snap = pipeline.snapshot()
    assert snap["tracks_active"] == 0
    assert snap["tracks_total"] == 0
    assert snap["dropped_tracks"] == 0


def test_close_releases_tracker() -> None:
    tracker = _ScriptedTracker([])
    pipeline = Pipeline(
        camera=FakeCamera(_frames(0)), detector=FakeDetector(_multi()), tracker=tracker
    )
    pipeline.close()
    assert tracker.closed is True
