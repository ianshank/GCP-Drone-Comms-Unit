"""Norfair backend (BSD-3-Clause) for the tracker seam.

Norfair is a lightweight, detector-agnostic Kalman-filter tracker: it consumes point
coordinates and returns tracked objects carrying a stable id. Here each detection's bbox
centre becomes a Norfair point; the returned objects are mapped back to their source
:class:`Detection` (attached as Norfair ``Detection.data``) and wrapped as
:class:`TrackedDetection`.

Two heavy-dep operations are isolated behind injectable seams so the id map-back logic is
unit-tested with fakes and no ``norfair``/``numpy`` are imported in tests (mirroring how
``ultralytics_backend`` injects a fake ``model``):

* ``tracker`` — the stateful ``norfair.Tracker`` (default built by :func:`_build_tracker`,
  ``# pragma: no cover``).
* ``to_detections`` — the source-``Detection``-tuple -> ``norfair.Detection`` list adapter
  (default :func:`_to_norfair_detections`, ``# pragma: no cover`` — the only place ``numpy``
  and ``norfair.Detection`` are constructed).

Norfair facts this backend relies on (verified against tryolabs/norfair 2.3.0):
``Tracker.__init__`` requires ``distance_threshold`` (no default) in **raw pixel units** for
the built-in ``"euclidean"`` distance; ``Tracker.update()`` returns ``List[TrackedObject]``;
objects still inside ``initialization_delay`` are withheld from that list and, if ever seen,
carry ``id is None`` — hence the defensive ``id is None`` skip below.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from ..core.config import TrackerSettings
from ..detection.base import Detection, DetectionResult
from .base import TrackedDetection, TrackerBase
from .factory import tracker_registry

#: Adapter: source detections -> the objects passed to ``norfair.Tracker.update``.
ToDetections = Callable[[Sequence[Detection]], list[Any]]


def _build_tracker(settings: TrackerSettings) -> Any:  # pragma: no cover - real norfair load
    import norfair

    return norfair.Tracker(
        distance_function=settings.distance_function,
        distance_threshold=settings.distance_threshold,
        hit_counter_max=settings.hit_counter_max,
        initialization_delay=settings.initialization_delay,
    )


def _to_norfair_detections(detections: Sequence[Detection]) -> list[Any]:  # pragma: no cover
    # Real numpy/norfair construction; the source Detection rides along as ``data`` so the
    # tracked object can be mapped back to it after association.
    import norfair
    import numpy as np

    out: list[Any] = []
    for det in detections:
        cx, cy = det.center
        out.append(norfair.Detection(points=np.array([[cx, cy]], dtype=float), data=det))
    return out


class NorfairTracker(TrackerBase):
    """Wraps a ``norfair.Tracker`` behind :class:`TrackerBase`."""

    def __init__(
        self,
        settings: TrackerSettings,
        *,
        tracker: Any | None = None,
        to_detections: ToDetections | None = None,
    ) -> None:
        self._settings = settings
        self._tracker = tracker if tracker is not None else _build_tracker(settings)
        self._to_detections: ToDetections = (
            to_detections if to_detections is not None else _to_norfair_detections
        )

    def update(self, result: DetectionResult) -> tuple[TrackedDetection, ...]:
        norfair_dets = self._to_detections(result.detections)
        tracked_objects = self._tracker.update(detections=norfair_dets)
        out: list[TrackedDetection] = []
        for obj in tracked_objects:
            track_id = getattr(obj, "id", None)
            if track_id is None:
                # Still initializing (or unassigned): no stable id this frame.
                continue
            out.append(TrackedDetection(detection=obj.last_detection.data, track_id=int(track_id)))
        return tuple(out)

    def close(self) -> None:
        self._tracker = None


@tracker_registry.register("norfair")
def _make_norfair(settings: TrackerSettings, **options: Any) -> NorfairTracker:
    return NorfairTracker(settings, **options)
