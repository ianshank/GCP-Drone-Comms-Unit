"""Norfair backend (BSD-3-Clause) for the tracker seam.

Norfair is a lightweight, detector-agnostic Kalman-filter tracker: it consumes point
coordinates and returns tracked objects carrying a stable id. Here each detection's bbox
centre becomes a Norfair point; the returned objects are mapped back to their source
:class:`Detection` (attached as Norfair ``Detection.data``) and wrapped as
:class:`TrackedDetection`.

Two heavy-dep operations are isolated behind injectable seams so the id map-back logic is
unit-tested with fakes and no ``norfair``/``numpy`` are imported by default (mirroring how
``ultralytics_backend`` injects a fake ``model``):

* ``tracker`` — the stateful ``norfair.Tracker`` (default built by :func:`_build_tracker`).
* ``to_detections`` — the source-``Detection``-tuple -> ``norfair.Detection`` list adapter
  (default :func:`_to_norfair_detections` — the only place ``numpy`` and ``norfair.Detection``
  are constructed).

Both defaults import ``norfair``/``numpy`` *inside* the function, so importing this module
never pulls them (locked by ``tests/unit/test_imports_clean.py``); they are exercised in tests
via injected fake ``sys.modules`` entries rather than ``# pragma: no cover``.

Norfair facts this backend relies on (verified against tryolabs/norfair 2.3.0):
``Tracker.__init__`` accepts a string ``distance_function`` (resolved via
``get_distance_by_name``) and requires ``distance_threshold`` (no default) in **raw pixel
units** for the built-in ``"euclidean"`` distance; ``Tracker.update()`` returns
``List[TrackedObject]`` including coasting/predicted tracks not matched this frame; objects
still inside ``initialization_delay`` are withheld and, if seen, carry ``id is None``. Ids are
assigned monotonically and never reused.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, Protocol, cast

import structlog

from ..core.config import TrackerSettings
from ..detection.base import Detection, DetectionResult
from .base import TrackedDetection, TrackerBase
from .factory import tracker_registry

_log = structlog.get_logger("jetson_yolo_gcs.tracking.norfair")

#: Adapter: source detections -> the objects passed to ``norfair.Tracker.update``.
ToDetections = Callable[[Sequence[Detection]], list[Any]]


class _TrackedObject(Protocol):
    """The subset of ``norfair.TrackedObject`` this backend reads."""

    #: Stable id, or ``None`` while the track is still initializing.
    id: int | None
    #: Most recent detection assigned to this track; ``.data`` is our source ``Detection``.
    last_detection: Any


class _NorfairTracker(Protocol):
    """The subset of ``norfair.Tracker`` this backend calls."""

    def update(self, detections: list[Any]) -> list[_TrackedObject]: ...


def _build_tracker(settings: TrackerSettings) -> _NorfairTracker:
    import norfair

    tracker = norfair.Tracker(
        distance_function=settings.distance_function,
        distance_threshold=settings.distance_threshold,
        hit_counter_max=settings.hit_counter_max,
        initialization_delay=settings.initialization_delay,
    )
    return cast("_NorfairTracker", tracker)


def _to_norfair_detections(detections: Sequence[Detection]) -> list[Any]:
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
        tracker: _NorfairTracker | None = None,
        to_detections: ToDetections | None = None,
    ) -> None:
        self._settings = settings
        self._tracker: _NorfairTracker | None = (
            tracker if tracker is not None else _build_tracker(settings)
        )
        self._to_detections: ToDetections = (
            to_detections if to_detections is not None else _to_norfair_detections
        )
        _log.debug(
            "norfair tracker built",
            distance_function=settings.distance_function,
            distance_threshold=settings.distance_threshold,
            hit_counter_max=settings.hit_counter_max,
            initialization_delay=settings.initialization_delay,
        )

    def update(self, result: DetectionResult) -> tuple[TrackedDetection, ...]:
        assert self._tracker is not None, "update() called after close()"
        norfair_dets = self._to_detections(result.detections)
        tracked_objects = self._tracker.update(detections=norfair_dets)
        # ``update`` returns every active track (``get_active_objects``), which INCLUDES
        # coasting/predicted tracks not matched this frame — for those, ``last_detection`` is a
        # Detection from an earlier frame. Emit only tracks matched to a detection in THIS frame
        # (identity check against the exact objects we passed as ``data``), so ``TrackedDetection``
        # always carries a current-frame detection, never a stale one.
        current_ids = {id(det) for det in result.detections}
        out: list[TrackedDetection] = []
        skipped_uninitialized = 0
        skipped_coasting = 0
        for obj in tracked_objects:
            track_id = obj.id
            if track_id is None:
                # Still initializing (or unassigned): no stable id this frame.
                skipped_uninitialized += 1
                continue
            last = obj.last_detection
            if last is None:
                # Defensive: a track with no detection carries no source to map back.
                continue
            source = last.data
            if id(source) not in current_ids:
                # Coasting/predicted track (not matched this frame): its detection is stale.
                skipped_coasting += 1
                continue
            out.append(
                TrackedDetection(detection=cast("Detection", source), track_id=int(track_id))
            )
        _log.debug(
            "norfair update",
            n_in=len(result.detections),
            n_confirmed=len(out),
            n_uninitialized=skipped_uninitialized,
            n_coasting=skipped_coasting,
        )
        return tuple(out)

    def close(self) -> None:
        # Terminal: the tracker is not reusable after close() (see TrackerBase.close).
        self._tracker = None


@tracker_registry.register("norfair")
def _make_norfair(settings: TrackerSettings, **options: Any) -> NorfairTracker:
    return NorfairTracker(settings, **options)
