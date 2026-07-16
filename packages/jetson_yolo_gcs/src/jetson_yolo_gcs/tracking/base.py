"""Tracker abstraction: the :class:`TrackerBase` ABC and the :class:`TrackedDetection`
value type.

The tracker sits *between* the per-frame detection registry and the pipeline. It consumes
a :class:`~jetson_yolo_gcs.detection.base.DetectionResult` and returns the subset of
detections that a multi-object tracker has associated to a **stable id** across frames.

Design notes (``docs/specs/initiative-d-perception.md`` tracking section):

* The stable id is carried by :class:`TrackedDetection` (a wrapper), **not** by mutating
  the frozen :class:`~jetson_yolo_gcs.detection.base.Detection` — so the detector's
  immutable value type keeps a single meaning and does not drift toward meshsa's wire model.
* Output is **advisory / read-only**: the pipeline uses it only for health-snapshot track
  counters. It never feeds ``LANDING_TARGET`` target selection (the safety write path).
* This is an ABC (mirrors :class:`~jetson_yolo_gcs.detection.base.DetectorBase`) so tests
  duck-type a fake and need no ``norfair``/GPU/hardware.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..detection.base import Detection, DetectionResult


@dataclass(frozen=True)
class TrackedDetection:
    """One detection the tracker has associated to a stable :attr:`track_id`.

    ``detection`` is the original, unmodified per-frame :class:`Detection`; ``track_id`` is
    the tracker's stable identifier for the physical object across frames (so one object is
    one id, not per-frame churn). A detection the tracker has not yet confirmed (e.g. still
    inside an initialization delay) is simply absent from the tracker's output for that frame.
    """

    detection: Detection
    track_id: int


class TrackerBase(ABC):
    """A swappable multi-object tracker. Backends implement :meth:`update`."""

    @abstractmethod
    def update(self, result: DetectionResult) -> tuple[TrackedDetection, ...]:
        """Associate this frame's detections to stable track ids.

        Returns one :class:`TrackedDetection` per track that is **confirmed and matched to a
        detection in this frame**; detections not yet confirmed, and confirmed-but-coasting
        tracks with no current-frame detection, are omitted (so ``tracks_active`` may dip while
        an object is briefly occluded even though the tracker still holds the track). At most
        one entry per source detection.

        Implementations are stateful across calls (they hold the track set) but must not perform
        any vehicle I/O. ``track_id`` values are expected to be assigned **monotonically and
        never reused** (the SORT/Kalman convention), which lets consumers count distinct tracks
        in O(1) memory instead of retaining every id.
        """
        raise NotImplementedError

    def close(self) -> None:
        """Release backend resources (default: no-op). **Terminal** — after ``close()`` the
        tracker is not reusable and :meth:`update` must not be called again."""
        return None
