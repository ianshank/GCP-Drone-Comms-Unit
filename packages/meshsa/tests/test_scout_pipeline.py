"""Tests for meshsa.scout.pipeline.ScoutPipeline — end-to-end + failure paths."""

from __future__ import annotations

from meshsa.config import ScoutConfig
from meshsa.cv.geo import Camera, Pose
from meshsa.models import Envelope, MessageKind
from meshsa.scout.cli import sample_block
from meshsa.scout.pipeline import ScoutPipeline
from meshsa.scout.pose import FusedPose
from meshsa.scout.replay import DEFAULT_CAMERA, ReplayFlight
from meshsa.scout.schemas import BBox, Block, PixelDetection
from meshsa.scout.terrain import FlatTerrain

CAM = Camera(img_w=1920, img_h=1080, h_fov_deg=70.0, v_fov_deg=42.0)


def _pipeline(emit=None, config: ScoutConfig | None = None) -> ScoutPipeline:
    block = sample_block()
    return ScoutPipeline(
        camera=DEFAULT_CAMERA,
        terrain=FlatTerrain(block.mean_elev_m),
        params=config or ScoutConfig(),
        block_id=block.block_id,
        emit=emit,
    )


def test_replay_end_to_end_three_pins() -> None:
    block = sample_block()
    flight = ReplayFlight(block, rtk_enabled=True, seed=1)
    emitted: list[Envelope] = []
    pipe = _pipeline(emit=emitted.append)
    pins = pipe.ingest(flight.poses, flight.detections)
    assert len(pins) == 3
    assert pipe.stats.projected == len(flight.detections)
    assert pipe.stats.dropped_skew == 0
    # Each emitted envelope is a positioned MARKER.
    assert emitted and all(e.kind == MessageKind.MARKER for e in emitted)
    assert all("position" in e.payload for e in emitted)


def _fp(ts: float, pitch: float = 90.0) -> FusedPose:
    return FusedPose(
        pose=Pose(lat=38.5, lon=-122.5, alt_agl_m=60.0, heading_deg=0.0, pitch_deg=pitch),
        roll_deg=0.0,
        ts=ts,
    )


def _det(ts: float, cx: float, cy: float) -> PixelDetection:
    return PixelDetection(
        frame_id=f"f{ts}",
        ts=ts,
        bbox=BBox(x1=cx - 5, y1=cy - 5, x2=cx + 5, y2=cy + 5),
        cls="missing_vine",
        conf=0.9,
    )


def test_skew_drop_counted() -> None:
    pipe = _pipeline()
    pipe.ingest([_fp(0.0)], [_det(100.0, CAM.img_w / 2, CAM.img_h * 0.3)])  # far skew
    assert pipe.stats.dropped_skew == 1
    assert pipe.stats.projected == 0


def test_horizon_drop_counted() -> None:
    pipe = _pipeline()
    # A near-horizon pose (pitch 10) + a top pixel -> depression below the minimum -> None.
    pipe.ingest([_fp(0.0, pitch=10.0)], [_det(0.0, CAM.img_w / 2, 0.0)])
    assert pipe.stats.dropped_horizon == 1
    assert pipe.stats.projected == 0


def test_default_store_used_when_not_injected() -> None:
    block = sample_block()
    flight = ReplayFlight(block, seed=1)
    pipe = _pipeline()
    pipe.ingest(flight.poses, flight.detections)
    assert len(pipe.store.all()) == 3


def test_large_survey_does_not_evict_early_poses() -> None:
    # Regression: a survey with far more poses than the default ring buffer (256) must not
    # evict early poses and drop their detections.
    big = Block(
        block_id="big",
        polygon=[(38.50, -122.50), (38.50, -122.4940), (38.5045, -122.4940), (38.5045, -122.50)],
        row_azimuth_deg=0.0,
        mean_elev_m=60.0,
        vine_spacing_m=2.0,
        row_spacing_m=2.4,
    )
    flight = ReplayFlight(big, rtk_enabled=True, seed=1)
    assert len(flight.poses) > 256  # exercises the eviction path
    pipe = ScoutPipeline(
        camera=DEFAULT_CAMERA,
        terrain=FlatTerrain(big.mean_elev_m),
        params=ScoutConfig(),
        block_id=big.block_id,
    )
    pins = pipe.ingest(flight.poses, flight.detections)
    assert len(pins) == len(flight.ground_truths)
    assert pipe.stats.projected > 0
    assert pipe.stats.dropped_skew == 0


def test_merge_preserves_persisted_triage() -> None:
    # Regression: an operator tag in the store must survive a later higher-confidence merge.
    pipe = _pipeline()
    pose = _fp(0.0)
    pipe.ingest(
        [pose],
        [
            PixelDetection(
                frame_id="f0",
                ts=0.0,
                bbox=BBox(x1=955, y1=535, x2=965, y2=545),
                cls="missing_vine",
                conf=0.5,
            )
        ],
    )
    (det_id,) = [d.id for d in pipe.store.all()]
    pipe.store.set_status(det_id, "tagged")
    # A second, higher-confidence observation of the same ground point merges into the cluster.
    pipe.ingest(
        [_fp(1.0)],
        [
            PixelDetection(
                frame_id="f1",
                ts=1.0,
                bbox=BBox(x1=955, y1=535, x2=965, y2=545),
                cls="missing_vine",
                conf=0.95,
            )
        ],
    )
    pins = pipe.ingest(
        [_fp(2.0)],
        [
            PixelDetection(
                frame_id="f2",
                ts=2.0,
                bbox=BBox(x1=955, y1=535, x2=965, y2=545),
                cls="missing_vine",
                conf=0.99,
            )
        ],
    )
    kept = pipe.store.get(det_id)
    assert kept is not None
    assert kept.status == "tagged"  # triage preserved despite the higher-conf merge
    # The returned pins reflect the persisted triage too, not the pre-merge dedup copy.
    assert [p.status for p in pins if p.id == det_id] == ["tagged"]


def test_dropped_skew_accumulates_across_batches() -> None:
    pipe = _pipeline()
    far = _det(100.0, CAM.img_w / 2, CAM.img_h * 0.3)  # no pose within skew
    pipe.ingest([_fp(0.0)], [far])
    pipe.ingest([_fp(0.0)], [far])
    assert pipe.stats.dropped_skew == 2  # accumulates, not reset per batch
