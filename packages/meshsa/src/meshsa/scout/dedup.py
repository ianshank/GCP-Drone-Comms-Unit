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
        self._clusters: list[GeoDetection] = []
        self.merges = 0

    def add(self, detection: GeoDetection) -> GeoDetection:
        """Add a detection; return the canonical (possibly pre-existing) cluster fix.

        On a merge the cluster keeps its original id and triage status but adopts the
        higher-confidence position, so an operator's tag/reject on a pin is not lost when
        a later, better frame arrives.
        """
        for i, rep in enumerate(self._clusters):
            if ground_distance_m(detection.lat, detection.lon, rep.lat, rep.lon) <= self._radius_m:
                self.merges += 1
                if detection.conf > rep.conf:
                    merged = detection.model_copy(
                        update={"id": rep.id, "status": rep.status, "block_id": rep.block_id}
                    )
                else:
                    merged = rep
                self._clusters[i] = merged
                _log.debug(
                    "detection_merged",
                    cluster_id=rep.id,
                    merges=self.merges,
                    clusters=len(self._clusters),
                )
                return merged
        self._clusters.append(detection)
        return detection

    def results(self) -> list[GeoDetection]:
        """Return the current deduplicated cluster representatives."""
        return list(self._clusters)
