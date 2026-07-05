"""Scout pipeline: sources -> sync -> georef -> dedup -> store -> emit (spec §3, Scout.4).

Wires a :class:`~meshsa.scout.protocols.PoseSource` and
:class:`~meshsa.scout.protocols.DetectionSource` through timestamp sync, georeferencing
(:func:`meshsa.cv.geo.project_to_ground`), spatial dedup, a :class:`~meshsa.scout.protocols.Store`,
and an optional MARKER sink. Each georeferenced detection is emitted through the **existing**
``DetectionCodec`` → MARKER ``Envelope`` (no codec edit), so a downstream TAK leg renders it in
ATAK. Per-path failure policy: a detection that cannot be synced or projected is **dropped and
counted**, never given a fabricated position.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass

import structlog

from ..config import ScoutConfig
from ..cv.geo import Camera, Terrain, project_to_ground
from ..detection_codec import DetectionCodec
from ..models import Envelope
from ..protocols import IdFactory, UuidFactory
from .dedup import Deduplicator
from .pose import FusedPose
from .protocols import Store
from .schemas import GeoDetection, PixelDetection
from .store import InMemoryStore
from .sync import TimeSync

_log = structlog.get_logger("meshsa.scout.pipeline")

#: Fallback source id for MARKER frames when a block id is not set.
_DEFAULT_SOURCE = "scout"

EmitSink = Callable[[Envelope], None]


@dataclass
class PipelineStats:
    """Counters for a pipeline run (observability / health-check assertions)."""

    detections_in: int = 0
    projected: int = 0
    dropped_skew: int = 0
    dropped_horizon: int = 0
    merges: int = 0
    pins: int = 0


class ScoutPipeline:
    """Deterministic offline/streaming scout pipeline."""

    def __init__(
        self,
        *,
        camera: Camera,
        terrain: Terrain,
        params: ScoutConfig,
        store: Store | None = None,
        ids: IdFactory | None = None,
        block_id: str | None = None,
        emit: EmitSink | None = None,
    ) -> None:
        self._cam = camera
        self._terrain = terrain
        self._params = params
        self._store: Store = store if store is not None else InMemoryStore()
        self._ids: IdFactory = ids if ids is not None else UuidFactory()
        self._block_id = block_id
        self._emit = emit
        self._sync = TimeSync(params.sync_max_skew_s)
        self._dedup = Deduplicator(params.dedup_radius_m)
        self._codec = DetectionCodec()
        self.stats = PipelineStats()

    @property
    def store(self) -> Store:
        return self._store

    def ingest(
        self, poses: Iterable[FusedPose], detections: Iterable[PixelDetection]
    ) -> list[GeoDetection]:
        """Process a batch: buffer poses, then sync+project+dedup+store each detection.

        The pose buffer is sized to the whole batch so a large survey (well over the default
        ring-buffer depth) does not evict early poses and silently drop their detections.
        """
        pose_list = list(poses)
        self._sync = TimeSync(self._params.sync_max_skew_s, buffer_size=max(1, len(pose_list)))
        for pose in pose_list:
            self._sync.add_pose(pose)
        for det in sorted(detections, key=lambda d: d.ts):
            self.stats.detections_in += 1
            fused = self._sync.align(det.ts)
            if fused is None:
                continue  # counted in self._sync.dropped
            fix = project_to_ground(
                fused.pose,
                self._cam,
                det.bbox.cx,
                det.bbox.cy,
                roll_deg=fused.roll_deg,
                terrain=self._terrain,
                pos_cep_m=self._params.pos_cep_m,
                att_sigma_deg=self._params.attitude_sigma_deg,
            )
            if fix is None:
                self.stats.dropped_horizon += 1
                _log.warning("projection_degraded", frame_id=det.frame_id, ts=det.ts)
                continue
            self.stats.projected += 1
            geo = GeoDetection(
                id=self._ids.new_id(),
                lat=fix.lat,
                lon=fix.lon,
                cls=det.cls,
                conf=det.conf,
                error_m=fix.ce_m,
                src_frame=det.frame_id,
                ts=det.ts,
                block_id=self._block_id,
            )
            canonical = self._dedup.add(geo)
            # Preserve any operator triage already persisted for this cluster: a later,
            # higher-confidence frame updates the position but must not reset a tag/reject.
            existing = self._store.get(canonical.id)
            if existing is not None and existing.status != "new":
                canonical = canonical.with_status(existing.status)
            self._store.add(canonical)
            if self._emit is not None:
                self._emit(self._to_envelope(canonical))
        self.stats.dropped_skew = self._sync.dropped
        self.stats.merges = self._dedup.merges
        self.stats.pins = len(self._dedup.results())
        _log.info(
            "ingest_complete",
            detections_in=self.stats.detections_in,
            projected=self.stats.projected,
            dropped_skew=self.stats.dropped_skew,
            dropped_horizon=self.stats.dropped_horizon,
            pins=self.stats.pins,
        )
        return self._dedup.results()

    def _to_envelope(self, det: GeoDetection) -> Envelope:
        """Reuse the existing detection codec to build a positioned MARKER envelope."""
        frame = {
            "src": det.block_id or _DEFAULT_SOURCE,
            "msg_id": det.id,
            "ts": det.ts,
            "lat": det.lat,
            "lon": det.lon,
            "ce": det.error_m,
            "label": det.cls,
            "confidence": det.conf,
        }
        return self._codec.decode(json.dumps(frame).encode("utf-8"))
