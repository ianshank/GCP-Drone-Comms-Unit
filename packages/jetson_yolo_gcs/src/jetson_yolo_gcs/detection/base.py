"""Detector abstraction: the :class:`DetectorBase` ABC and frozen result types.

The dataclasses are immutable (mirrors meshsa's frozen-dataclass style) so a result
can be passed through the pipeline without defensive copies. ``frame`` is typed
``Any`` so no numpy/opencv type leaks into the pure code path.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Detection:
    """One detected object in image (pixel) coordinates."""

    class_id: int
    class_name: str
    confidence: float
    #: Bounding box ``(x1, y1, x2, y2)`` in pixels (top-left, bottom-right).
    bbox: tuple[float, float, float, float]

    @property
    def center(self) -> tuple[float, float]:
        """Pixel centre ``(cx, cy)`` of the bounding box."""
        x1, y1, x2, y2 = self.bbox
        return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)


@dataclass(frozen=True)
class DetectionResult:
    """All detections for one frame plus the frame geometry."""

    detections: tuple[Detection, ...]
    width: int
    height: int

    def best(self) -> Detection | None:
        """Highest-confidence detection, or ``None`` when the frame is empty."""
        return max(self.detections, key=lambda d: d.confidence, default=None)


class DetectorBase(ABC):
    """A swappable object detector. Backends implement :meth:`detect`."""

    @abstractmethod
    def detect(self, frame: Any) -> DetectionResult:
        """Run inference on one frame buffer and return its detections."""
        raise NotImplementedError

    def close(self) -> None:
        """Release any backend resources (default: no-op)."""
        return None
