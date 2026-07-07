"""Full pipeline with mocked I/O: detection flows to stream + LANDING_TARGET,
and the loop's path-specific error/idle handling behaves as designed."""

from __future__ import annotations

from typing import Any

import pytest

from jetson_yolo_gcs.core.config import MavlinkSettings
from jetson_yolo_gcs.core.errors import DetectionError
from jetson_yolo_gcs.detection.base import Detection, DetectionResult
from jetson_yolo_gcs.mavlink.bridge import LandingTargetBridge
from jetson_yolo_gcs.mavlink.pose import VehiclePose
from jetson_yolo_gcs.pipeline import Pipeline, _should_log_drop
from jetson_yolo_gcs.streaming.camera import Frame
from jetson_yolo_gcs.utils.fps import FpsCounter
from tests.conftest import FakeCamera, FakeClock, FakeDetector, FakeStreamWriter


class _RecordingMav:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def landing_target_send(self, *args: object) -> None:
        self.calls.append(args)


class _RecordingConn:
    def __init__(self, heartbeats: list[object] | None = None) -> None:
        self.mav = _RecordingMav()
        self._inbox: list[object] = list(heartbeats or [])

    def recv_match(self, *, type: str, blocking: bool) -> object | None:  # noqa: A002
        return self._inbox.pop(0) if self._inbox else None

    def close(self) -> None:
        pass


class _Heartbeat:
    """Duck-typed HEARTBEAT from system/component 1 (the default target autopilot)."""

    def get_srcSystem(self) -> int:  # noqa: N802 - pymavlink accessor name
        return 1

    def get_srcComponent(self) -> int:  # noqa: N802 - pymavlink accessor name
        return 1


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


def _bridge(conn: object, *, require_heartbeat: bool = False) -> LandingTargetBridge:
    """Bridge for pipeline tests. The fail-closed gate defaults *off* here — it is covered
    in ``test_mavlink_bridge.py``; most pipeline tests exercise the publish/count paths and
    want the gate open. Pass ``require_heartbeat=True`` for the gated integration cases.
    """
    return LandingTargetBridge(
        MavlinkSettings(enable_landing_target=True, require_heartbeat=require_heartbeat),
        connection=conn,
    )


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


class _FixedPose:
    """A :class:`PoseSource` fake returning a caller-supplied pose (or ``None``) forever."""

    def __init__(self, pose: VehiclePose | None) -> None:
        self._pose = pose

    def latest(self) -> VehiclePose | None:
        return self._pose


def test_full_step_publishes_local_ned_end_to_end_with_fixed_pose() -> None:
    # End-to-end (fakes): frame="local_ned" + a fixed pose -> one landing_target_send with
    # MAV_FRAME_LOCAL_NED (1) and position_valid=1, wired the same way a real deployment would.
    conn = _RecordingConn()
    bridge = LandingTargetBridge(
        MavlinkSettings(enable_landing_target=True, require_heartbeat=False, frame="local_ned"),
        connection=conn,
        pose_source=_FixedPose(VehiclePose(alt_agl_m=100.0, heading_deg=0.0, pitch_deg=90.0)),
    )
    pipeline = Pipeline(
        camera=FakeCamera(_frames(1)),
        detector=FakeDetector(_sample()),
        bridge=bridge,
    )
    assert pipeline.step() is True
    assert len(conn.mav.calls) == 1
    args = conn.mav.calls[0]
    assert args[2] == 1  # MAV_FRAME_LOCAL_NED
    assert args[-1] == 1  # position_valid
    assert pipeline.landing_target_published == 1


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


class _RaisingMav:
    def landing_target_send(self, *args: object) -> None:
        raise RuntimeError("link down")


class _RaisingConn:
    def __init__(self) -> None:
        self.mav = _RaisingMav()

    def recv_match(self, *, type: str, blocking: bool) -> object | None:  # noqa: A002
        return None

    def close(self) -> None:
        pass


def test_publish_failure_tolerated_below_threshold() -> None:
    # A single transient publish failure is counted and logged, but does NOT crash the loop
    # (tolerance defaults to 3): step() still returns True and the camera+stream loop survives.
    pipeline = Pipeline(
        camera=FakeCamera(_frames(1)),
        detector=FakeDetector(_sample()),
        bridge=_bridge(_RaisingConn()),
    )
    assert pipeline.step() is True
    assert pipeline.landing_target_publish_failures == 1
    assert pipeline.landing_target_published == 0


def test_publish_failure_escalates_on_first_when_tolerance_zero() -> None:
    # tolerance=0 = fail loud on the first failure (the tightest setting preserves the old
    # crash-on-broken-safety-feed contract).
    pipeline = Pipeline(
        camera=FakeCamera(_frames(1)),
        detector=FakeDetector(_sample()),
        bridge=_bridge(_RaisingConn()),
        publish_failure_tolerance=0,
    )
    with pytest.raises(RuntimeError):
        pipeline.step()
    assert pipeline.landing_target_publish_failures == 1


def test_publish_failures_escalate_past_tolerance() -> None:
    # tolerance=2: failures 1 and 2 are tolerated; the 3rd consecutive (> tolerance) escalates.
    pipeline = Pipeline(
        camera=FakeCamera(_frames(3)),
        detector=FakeDetector(_sample()),
        bridge=_bridge(_RaisingConn()),
        publish_failure_tolerance=2,
    )
    assert pipeline.step() is True  # failure 1 tolerated
    assert pipeline.step() is True  # failure 2 tolerated
    with pytest.raises(RuntimeError):
        pipeline.step()  # failure 3 (> 2) -> escalate
    assert pipeline.landing_target_publish_failures == 3


def test_consecutive_failures_reset_on_success() -> None:
    # A successful send between failures resets the consecutive streak (so escalation only
    # fires on a *persistent* run of failures, not a scattered few).
    conn = _RaisingConn()
    pipeline = Pipeline(
        camera=FakeCamera(_frames(3)),
        detector=FakeDetector(_sample()),
        bridge=_bridge(conn),
        publish_failure_tolerance=5,  # high so nothing escalates during this test
    )
    assert pipeline.step() is True  # failure 1
    assert pipeline.step() is True  # failure 2
    assert pipeline._consecutive_publish_failures == 2
    conn.mav = _RecordingMav()  # link recovers -> next send succeeds
    assert pipeline.step() is True
    assert pipeline._consecutive_publish_failures == 0  # reset on the successful send
    assert pipeline.landing_target_published == 1
    assert pipeline.landing_target_publish_failures == 2


def test_suppression_does_not_reset_failure_streak() -> None:
    # A gate suppression between two failures must NOT clear the streak — otherwise an
    # intermittently-fresh link with a persistently broken send would never escalate.
    outcomes: list[str] = ["raise", "suppress", "raise"]

    class _ScriptedBridge(LandingTargetBridge):
        def publish(self, detection: Detection, result: DetectionResult) -> bool:
            outcome = outcomes.pop(0)
            if outcome == "raise":
                raise RuntimeError("link down")
            return False  # suppressed (gate closed)

        def poll_heartbeat(self) -> bool:
            return False

    bridge = _ScriptedBridge(
        MavlinkSettings(enable_landing_target=True, require_heartbeat=False),
        connection=_RecordingConn(),
    )
    pipeline = Pipeline(
        camera=FakeCamera(_frames(3)),
        detector=FakeDetector(_sample()),
        bridge=bridge,
        publish_failure_tolerance=1,
    )
    assert pipeline.step() is True  # raise -> consecutive=1 (tolerated, 1 not > 1)
    assert pipeline.step() is True  # suppress -> streak preserved, not reset
    assert pipeline.landing_target_suppressed == 1
    with pytest.raises(RuntimeError):
        pipeline.step()  # raise -> consecutive=2 (> 1) -> escalate despite the suppression
    assert pipeline.landing_target_publish_failures == 2


def test_step_polls_heartbeat_then_publishes_when_fresh() -> None:
    conn = _RecordingConn(heartbeats=[_Heartbeat()])
    pipeline = Pipeline(
        camera=FakeCamera(_frames(1)),
        detector=FakeDetector(_sample()),
        bridge=_bridge(conn, require_heartbeat=True),
    )
    assert pipeline.step() is True
    assert len(conn.mav.calls) == 1  # heartbeat polled -> gate open -> published
    assert pipeline.landing_target_published == 1
    assert pipeline.landing_target_suppressed == 0


def test_step_suppresses_publish_without_heartbeat() -> None:
    conn = _RecordingConn()  # no heartbeat available to poll
    pipeline = Pipeline(
        camera=FakeCamera(_frames(1)),
        detector=FakeDetector(_sample()),
        bridge=_bridge(conn, require_heartbeat=True),
    )
    assert pipeline.step() is True  # loop survives the fail-closed suppression
    assert conn.mav.calls == []
    assert pipeline.landing_target_published == 0
    assert pipeline.landing_target_suppressed == 1


def test_cadence_violation_counted_when_gap_exceeds_floor() -> None:
    # min_publish_rate_hz=10 -> a >0.1 s gap between publishes is a cadence violation.
    conn = _RecordingConn()
    pipeline = Pipeline(
        camera=FakeCamera(_frames(2)),
        detector=FakeDetector(_sample()),
        bridge=_bridge(conn),
        # Two clock reads per publishing step (frame stamp, then cadence stamp):
        clock=FakeClock(times=[100.0, 100.0, 101.0, 101.0]),
        fps=FpsCounter(clock=FakeClock()),
        min_publish_rate_hz=10.0,
    )
    assert pipeline.step() is True  # 1st publish: no prior -> no violation
    assert pipeline.step() is True  # 2nd publish: 1.0 s gap > 0.1 s floor -> violation
    assert pipeline.landing_target_published == 2
    assert pipeline.landing_target_cadence_violations == 1


def test_cadence_exactly_at_floor_is_not_a_violation() -> None:
    # A gap exactly equal to 1/min_rate is on-cadence (strict `>`), not a violation.
    conn = _RecordingConn()
    pipeline = Pipeline(
        camera=FakeCamera(_frames(2)),
        detector=FakeDetector(_sample()),
        bridge=_bridge(conn),
        # 2nd publish cadence stamp is exactly 0.1 s after the 1st (100.0 -> 100.1).
        clock=FakeClock(times=[100.0, 100.0, 100.0, 100.1]),
        fps=FpsCounter(clock=FakeClock()),
        min_publish_rate_hz=10.0,  # floor = exactly 0.1 s
    )
    assert pipeline.step() is True
    assert pipeline.step() is True
    assert pipeline.landing_target_published == 2
    assert pipeline.landing_target_cadence_violations == 0


def test_snapshot_reports_heartbeat_freshness() -> None:
    # Gate on, no beat -> heartbeat_fresh False (the observable "silent suppression" signal);
    # after a fresh beat is polled -> True. No bridge / gate off -> None.
    conn = _RecordingConn(heartbeats=[_Heartbeat()])
    gated = Pipeline(
        camera=FakeCamera(_frames(1)),
        detector=FakeDetector(_sample()),
        bridge=_bridge(conn, require_heartbeat=True),
    )
    assert gated.snapshot()["landing_target_heartbeat_fresh"] is False  # no beat yet
    assert gated.step() is True  # polls the heartbeat -> gate opens
    assert gated.snapshot()["landing_target_heartbeat_fresh"] is True

    no_gate = Pipeline(camera=FakeCamera(_frames(0)), detector=FakeDetector(_sample()))
    assert no_gate.snapshot()["landing_target_heartbeat_fresh"] is None  # no bridge


@pytest.mark.parametrize(
    "kwargs",
    [
        {"liveness_timeout_s": 0.0},
        {"drop_log_every": 0},
        {"min_publish_rate_hz": 0.0},
        {"publish_failure_tolerance": -1},
    ],
)
def test_pipeline_rejects_out_of_range_invariants(kwargs: dict[str, float]) -> None:
    # The class enforces its own contract independent of config Field bounds, so a direct
    # construction can't build a self-inconsistent loop (e.g. drop_log_every=0 -> ZeroDivision).
    with pytest.raises(ValueError):
        Pipeline(camera=FakeCamera(_frames(0)), detector=FakeDetector(_sample()), **kwargs)


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
        def publish(self, detection: Detection, result: DetectionResult) -> bool:
            captured.append(detection)
            return True

    bridge = _CapturingBridge(
        MavlinkSettings(enable_landing_target=True, require_heartbeat=False),
        connection=_RecordingConn(),
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


def test_snapshot_counts_and_reports_live() -> None:
    conn = _RecordingConn()
    pipeline = Pipeline(
        camera=FakeCamera(_frames(1)),
        detector=FakeDetector(_sample()),
        bridge=_bridge(conn),
        # Reads per step: frame stamp (100.0), publish-cadence stamp (100.5); then snapshot (101.0).
        clock=FakeClock(times=[100.0, 100.5, 101.0]),
        fps=FpsCounter(clock=FakeClock()),  # isolated so the pipeline clock only times frames
    )
    assert pipeline.step() is True
    snap = pipeline.snapshot(max_age_s=2.0)
    assert snap["landing_target_published"] == 1
    assert snap["landing_target_suppressed"] == 0
    assert snap["landing_target_cadence_violations"] == 0
    assert snap["landing_target_publish_failures"] == 0
    assert snap["last_frame_age_s"] == 1.0
    assert snap["live"] is True


def test_snapshot_not_live_when_stale() -> None:
    pipeline = Pipeline(
        camera=FakeCamera(_frames(1)),
        detector=FakeDetector(_sample()),
        clock=FakeClock(times=[100.0, 105.0]),  # 5s since last frame
        fps=FpsCounter(clock=FakeClock()),
    )
    pipeline.step()
    snap = pipeline.snapshot(max_age_s=2.0)
    assert snap["last_frame_age_s"] == 5.0
    assert snap["live"] is False


def test_snapshot_before_any_frame_is_not_live() -> None:
    pipeline = Pipeline(camera=FakeCamera(_frames(0)), detector=FakeDetector(_sample()))
    snap = pipeline.snapshot()
    assert snap["live"] is False
    assert snap["last_frame_age_s"] is None
    assert snap["landing_target_published"] == 0


def test_snapshot_uses_configured_liveness_timeout() -> None:
    # 5s since the last frame: live under a 10s timeout, but would be dead under the 2s default.
    pipeline = Pipeline(
        camera=FakeCamera(_frames(1)),
        detector=FakeDetector(_sample()),
        clock=FakeClock(times=[100.0, 105.0]),
        fps=FpsCounter(clock=FakeClock()),
        liveness_timeout_s=10.0,
    )
    pipeline.step()
    snap = pipeline.snapshot()  # no explicit max_age_s -> uses the configured 10.0
    assert snap["last_frame_age_s"] == 5.0
    assert snap["live"] is True


@pytest.mark.parametrize(
    ("count", "every", "expected"),
    [(1, 100, True), (2, 100, False), (100, 100, True), (200, 100, True), (3, 1, True)],
)
def test_should_log_drop(count: int, every: int, expected: bool) -> None:
    assert _should_log_drop(count, every) is expected


def test_repeated_detection_drops_are_counted_not_relogged() -> None:
    class _AlwaysRaises:
        def detect(self, frame: Any) -> DetectionResult:
            raise DetectionError("bad")

        def close(self) -> None:
            pass

    pipeline = Pipeline(camera=FakeCamera(_frames(2)), detector=_AlwaysRaises())
    assert pipeline.run(max_consecutive_empty=1) == 2  # both frames read despite drops
    assert pipeline.dropped_detections == 2  # 2nd drop exercises the no-relog branch


def test_run_respects_max_iterations() -> None:
    camera = FakeCamera(_frames(5))
    detector = FakeDetector(_sample())
    pipeline = Pipeline(camera=camera, detector=detector)
    assert pipeline.run(max_iterations=2) == 2  # stops at the bound, not end-of-stream
    assert detector.calls == 2


def test_close_swallows_raising_closer() -> None:
    class _RaisingCamera:
        def read_frame(self) -> Frame | None:
            return None

        def close(self) -> None:
            raise OSError("device busy")

    pipeline = Pipeline(camera=_RaisingCamera(), detector=FakeDetector(_sample()))
    pipeline.close()  # must not raise
