"""Timestamp alignment of detections to poses (spec §4, Scout.2).

A detection is only as well-located as the pose it is projected against. ``TimeSync``
buffers recent poses and matches each detection to the **nearest** by timestamp; if the
skew exceeds ``max_skew_s`` the detection is **dropped and counted** rather than projected
against a stale pose (which would silently mislocate the pin).
"""

from __future__ import annotations

import bisect
from collections import deque

import structlog

from .pose import FusedPose

_log = structlog.get_logger("meshsa.scout.sync")

#: Default ring-buffer depth for recent poses.
_DEFAULT_BUFFER = 256


class TimeSync:
    """Nearest-timestamp pose matcher with a max-skew guard.

    Aligning a full survey is O(detections × poses) with a linear nearest scan; instead the
    buffer is sorted by timestamp **once** (lazily, on the first ``align`` after any
    ``add_pose``) and each lookup is an O(log n) binary search over the two straddling poses.
    Correct regardless of insertion order.
    """

    def __init__(self, max_skew_s: float, *, buffer_size: int = _DEFAULT_BUFFER) -> None:
        self._max_skew_s = max_skew_s
        self._poses: deque[FusedPose] = deque(maxlen=buffer_size)
        self._sorted: list[FusedPose] | None = None
        self._sorted_ts: list[float] = []
        self.dropped = 0

    def add_pose(self, pose: FusedPose) -> None:
        """Buffer a pose sample for later alignment (invalidates the sorted index)."""
        self._poses.append(pose)
        self._sorted = None

    def align(self, ts: float) -> FusedPose | None:
        """Return the nearest buffered pose to ``ts`` within ``max_skew_s``, else ``None``.

        Increments :attr:`dropped` and logs when no pose is close enough — the caller
        must treat ``None`` as "do not project this detection".
        """
        if not self._poses:
            self.dropped += 1
            _log.warning("no_pose_for_detection", ts=ts, dropped=self.dropped)
            return None
        if self._sorted is None:
            self._sorted = sorted(self._poses, key=lambda p: p.ts)
            self._sorted_ts = [p.ts for p in self._sorted]
        i = bisect.bisect_left(self._sorted_ts, ts)
        best: FusedPose | None = None
        best_skew = float("inf")
        for j in (i - 1, i):  # the two poses straddling ts are the nearest candidates
            if 0 <= j < len(self._sorted):
                skew = abs(self._sorted[j].ts - ts)
                if skew < best_skew:
                    best_skew = skew
                    best = self._sorted[j]
        if best is None or best_skew > self._max_skew_s:
            self.dropped += 1
            _log.warning(
                "pose_skew_exceeded",
                ts=ts,
                skew_s=best_skew,
                max_skew_s=self._max_skew_s,
                dropped=self.dropped,
            )
            return None
        return best
