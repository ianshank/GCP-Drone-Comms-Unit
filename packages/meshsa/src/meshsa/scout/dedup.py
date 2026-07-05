"""Spatial deduplication of georeferenced detections (spec §4, Scout.2).

One physical anomaly is seen in many overlapping frames. ``Deduplicator`` collapses
detections that land within ``radius_m`` of an existing cluster into a single
``GeoDetection`` (keeping the cluster's stable id and the highest-confidence fix). At
the A1 tier ``radius_m ≈ vine_spacing/2``; under RTK noise a truth collapses to exactly
one pin, while under M8N-level noise clusters merge across vines — the empirical proof
(regression-tested) that A1 needs RTK.
"""

from __future__ import annotations

import structlog

from ..cv.geo import ground_distance_m
from .schemas import GeoDetection

_log = structlog.get_logger("meshsa.scout.dedup")


class Deduplicator:
    """Greedy single-link spatial clustering by ground distance."""

    def __init__(self, radius_m: float) -> None:
        self._radius_m = radius_m
        self._reps: list[GeoDetection] = []
        #: Each cluster's **original** position, used as the fixed membership anchor so the
        #: representative adopting higher-confidence fixes cannot "chain" the cluster location
        #: cumulatively beyond ``radius_m`` (the single-linkage failure mode).
        self._anchors: list[tuple[float, float]] = []
        self.merges = 0

    def add(self, detection: GeoDetection) -> GeoDetection:
        """Add a detection; return the canonical (possibly pre-existing) cluster fix.

        Membership is tested against each cluster's fixed anchor (its first detection), so a
        run of higher-confidence merges can refine the *reported* position but never drift the
        cluster beyond ``radius_m`` of where it started. On a merge the cluster keeps its stable
        id and triage status but adopts the higher-confidence position.
        """
        for i, (anchor_lat, anchor_lon) in enumerate(self._anchors):
            if (
                ground_distance_m(detection.lat, detection.lon, anchor_lat, anchor_lon)
                <= self._radius_m
            ):
                self.merges += 1
                rep = self._reps[i]
                if detection.conf > rep.conf:
                    merged = detection.model_copy(
                        update={"id": rep.id, "status": rep.status, "block_id": rep.block_id}
                    )
                else:
                    merged = rep
                self._reps[i] = merged
                _log.debug(
                    "detection_merged",
                    cluster_id=rep.id,
                    merges=self.merges,
                    clusters=len(self._reps),
                )
                return merged
        self._reps.append(detection)
        self._anchors.append((detection.lat, detection.lon))
        return detection

    def results(self) -> list[GeoDetection]:
        """Return the current deduplicated cluster representatives."""
        return list(self._reps)
