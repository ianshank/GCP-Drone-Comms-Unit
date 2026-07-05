"""Synthetic replay harness — NO HARDWARE (spec §1 Scout.0).

Simulates a boustrophedon survey over a :class:`~meshsa.scout.schemas.Block`, emitting a
:class:`~meshsa.scout.pose.FusedPose` stream and :class:`~meshsa.scout.schemas.PixelDetection`
frames at a handful of **known ground-truth** anomalies. Detections are placed by inverse
projection against the *true* pose, while the *reported* pose carries configurable
position/attitude noise (RTK cm-level vs M8N metre-level) — so downstream georef+dedup can be
asserted against truth, and the M8N-vs-RTK dedup behaviour is reproducible.

Determinism: a seeded :class:`random.Random` (no global RNG), so the same seed yields the
same flight — safe for regression tests and the ``--health-check``.
"""

from __future__ import annotations

import math
import random
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field

import structlog

from ..cv.geo import Camera, Pose, destination, ground_distance_m, initial_bearing
from .pose import NADIR_DEPRESSION_DEG, FusedPose
from .schemas import BBox, Block, PixelDetection
from .survey import footprints_m

_log = structlog.get_logger("meshsa.scout.replay")

#: Default synthetic pinhole camera (approx a 70°×42° RGB sensor at 1080p).
DEFAULT_CAMERA = Camera(img_w=1920, img_h=1080, h_fov_deg=70.0, v_fov_deg=42.0)
#: Noise 1σ presets (position m, attitude deg) for the RTK vs stock-M8N tiers. The RTK
#: position σ mirrors ``ScoutConfig.pos_cep_m`` (cm-level); kept local to this synthetic
#: harness (not production config) but cross-referenced to avoid drift.
_RTK_POS_SIGMA_M, _RTK_ATT_SIGMA_DEG = 0.05, 0.2
_M8N_POS_SIGMA_M, _M8N_ATT_SIGMA_DEG = 2.5, 1.0
#: Vertical GNSS error runs larger than horizontal on consumer receivers; scale the
#: position σ to give the reported AGL a representative altitude-error term.
_VERTICAL_NOISE_FACTOR = 1.5


@dataclass(frozen=True)
class GroundTruth:
    """A known anomaly location injected into the synthetic flight."""

    lat: float
    lon: float
    cls: str = "missing_vine"


def _bbox(block: Block) -> tuple[float, float, float, float]:
    lats = [p[0] for p in block.polygon]
    lons = [p[1] for p in block.polygon]
    return min(lats), max(lats), min(lons), max(lons)


def _default_truths(row_lats: Sequence[float], min_lon: float, max_lon: float) -> list[GroundTruth]:
    """Three well-separated anomalies placed **on** distinct transect lines.

    Placing each truth on a row's latitude means the aircraft flies straight at it, so it
    falls in the projector's well-conditioned forward wedge (low yaw offset) across several
    frames — the geometry georef+dedup are designed for. Distinct rows keep the truths far
    apart (>> dedup radius), so under RTK noise they dedupe to exactly three pins.
    """
    n = len(row_lats)
    idxs = sorted({max(0, n // 4), n // 2, min(n - 1, (3 * n) // 4)})
    fracs = [0.35, 0.5, 0.65]
    return [
        GroundTruth(lat=row_lats[i], lon=min_lon + f * (max_lon - min_lon))
        for i, f in zip(idxs, fracs, strict=False)
    ]


def _truth_to_pixel(
    pose: Pose, cam: Camera, tlat: float, tlon: float
) -> tuple[float, float] | None:
    """Inverse projection: pixel a ground truth lands on, or ``None`` if outside the FOV."""
    rng = ground_distance_m(pose.lat, pose.lon, tlat, tlon)
    depression = NADIR_DEPRESSION_DEG if rng <= 0 else math.degrees(math.atan2(pose.alt_agl_m, rng))
    pitch_off = depression - pose.pitch_deg
    brg = pose.heading_deg if rng <= 0 else initial_bearing(pose.lat, pose.lon, tlat, tlon)
    yaw_off = ((brg - pose.heading_deg + 180.0) % 360.0) - 180.0
    # Reject anything not in the forward hemisphere: tan() has period 180°, so a target
    # *behind* the camera (|yaw_off|→180) would otherwise alias onto a valid centre pixel.
    if not (-90.0 < yaw_off < 90.0 and -90.0 < pitch_off < 90.0):
        return None
    half_h = math.tan(math.radians(cam.h_fov_deg / 2.0))
    half_v = math.tan(math.radians(cam.v_fov_deg / 2.0))
    fx = math.tan(math.radians(yaw_off)) / half_h
    fy = math.tan(math.radians(pitch_off)) / half_v
    if not (-1.0 <= fx <= 1.0 and -1.0 <= fy <= 1.0):
        return None
    return (fx + 1.0) / 2.0 * cam.img_w, (fy + 1.0) / 2.0 * cam.img_h


@dataclass
class ReplayFlight:
    """A precomputed synthetic survey: fused poses, detections, and the ground truths.

    ``rtk_enabled`` selects the noise tier unless ``pos_noise_m`` / ``att_noise_deg`` are
    given explicitly (the dedup regression test sets M8N noise directly).
    """

    block: Block
    camera: Camera = DEFAULT_CAMERA
    alt_agl_m: float = 60.0
    forward_overlap: float = 0.75
    side_overlap: float = 0.65
    rtk_enabled: bool = True
    seed: int = 0
    dt_s: float = 0.1
    conf: float = 0.9
    truths: Sequence[GroundTruth] | None = None
    pos_noise_m: float | None = None
    att_noise_deg: float | None = None
    poses: list[FusedPose] = field(default_factory=list, init=False)
    detections: list[PixelDetection] = field(default_factory=list, init=False)
    ground_truths: list[GroundTruth] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        rng = random.Random(self.seed)
        pos_sigma = (
            self.pos_noise_m
            if self.pos_noise_m is not None
            else (_RTK_POS_SIGMA_M if self.rtk_enabled else _M8N_POS_SIGMA_M)
        )
        att_sigma = (
            self.att_noise_deg
            if self.att_noise_deg is not None
            else (_RTK_ATT_SIGMA_DEG if self.rtk_enabled else _M8N_ATT_SIGMA_DEG)
        )
        self._build(rng, pos_sigma, att_sigma)
        _log.info(
            "replay_built",
            poses=len(self.poses),
            detections=len(self.detections),
            truths=len(self.ground_truths),
            rtk=self.rtk_enabled,
        )

    def _footprints_m(self) -> tuple[float, float]:
        """Ground footprint (cross-track, along-track) in metres at ``alt_agl_m``.

        Delegates to the survey planner's helper so the replay harness (trusted as ground
        truth by ``--health-check``) and the planner never disagree on footprint geometry.
        """
        return footprints_m(self.camera.h_fov_deg, self.camera.v_fov_deg, self.alt_agl_m)

    def _row_latitudes(
        self, min_lat: float, max_lat: float, min_lon: float, row_step_m: float
    ) -> list[float]:
        lats: list[float] = []
        lat = min_lat
        while lat <= max_lat:
            lats.append(lat)
            lat = destination(lat, min_lon, 0.0, row_step_m)[0]
        return lats

    def _build(self, rng: random.Random, pos_sigma: float, att_sigma: float) -> None:
        min_lat, max_lat, min_lon, max_lon = _bbox(self.block)
        cross_m, along_m = self._footprints_m()
        row_step_m = max(1.0, cross_m * (1.0 - self.side_overlap))
        step_m = max(1.0, along_m * (1.0 - self.forward_overlap))
        span_m = ground_distance_m(min_lat, min_lon, min_lat, max_lon)
        n_steps = max(1, int(span_m / step_m))
        row_lats = self._row_latitudes(min_lat, max_lat, min_lon, row_step_m)
        self.ground_truths = (
            list(self.truths)
            if self.truths is not None
            else _default_truths(row_lats, min_lon, max_lon)
        )
        ts = 0.0
        frame = 0
        for row_i, lat in enumerate(row_lats):
            heading = 90.0 if row_i % 2 == 0 else 270.0
            for i in range(n_steps + 1):
                east_m = i * step_m if heading == 90.0 else (n_steps - i) * step_m
                _plat, plon = destination(lat, min_lon, 90.0, east_m)
                true_pose = Pose(
                    lat=lat,
                    lon=plon,
                    alt_agl_m=self.alt_agl_m,
                    heading_deg=heading,
                    pitch_deg=NADIR_DEPRESSION_DEG,
                )
                self._emit(true_pose, ts, frame, rng, pos_sigma, att_sigma)
                ts += self.dt_s
                frame += 1

    def _emit(
        self,
        true_pose: Pose,
        ts: float,
        frame: int,
        rng: random.Random,
        pos_sigma: float,
        att_sigma: float,
    ) -> None:
        # Reported (noisy) pose is what the pipeline projects with.
        if pos_sigma > 0:
            b = rng.uniform(0.0, 360.0)
            r = abs(rng.gauss(0.0, pos_sigma))
            nlat, nlon = destination(true_pose.lat, true_pose.lon, b, r)
        else:
            nlat, nlon = true_pose.lat, true_pose.lon
        alt_noise = rng.gauss(0.0, pos_sigma * _VERTICAL_NOISE_FACTOR)
        reported = Pose(
            lat=nlat,
            lon=nlon,
            alt_agl_m=max(1.0, true_pose.alt_agl_m + alt_noise),
            heading_deg=(true_pose.heading_deg + rng.gauss(0.0, att_sigma)) % 360.0,
            pitch_deg=true_pose.pitch_deg + rng.gauss(0.0, att_sigma),
        )
        self.poses.append(FusedPose(pose=reported, roll_deg=0.0, ts=ts))
        # Detections are placed by the TRUE pose (where the sensor actually sees them).
        for gt in self.ground_truths:
            px = _truth_to_pixel(true_pose, self.camera, gt.lat, gt.lon)
            if px is None:
                continue
            cx, cy = px
            self.detections.append(
                PixelDetection(
                    frame_id=f"f{frame}",
                    ts=ts,
                    bbox=BBox(x1=cx - 10.0, y1=cy - 10.0, x2=cx + 10.0, y2=cy + 10.0),
                    cls=gt.cls,
                    conf=self.conf,
                )
            )


class ReplayPoseSource:
    """A :class:`~meshsa.scout.protocols.PoseSource` over a precomputed flight."""

    def __init__(self, flight: ReplayFlight) -> None:
        self._flight = flight

    async def stream(self) -> AsyncIterator[FusedPose]:
        for pose in self._flight.poses:
            yield pose


class ReplayDetectionSource:
    """A :class:`~meshsa.scout.protocols.DetectionSource` over a precomputed flight."""

    def __init__(self, flight: ReplayFlight) -> None:
        self._flight = flight

    async def stream(self) -> AsyncIterator[PixelDetection]:
        for det in self._flight.detections:
            yield det
