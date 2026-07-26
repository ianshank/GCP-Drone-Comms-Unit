"""Bounded current-picture snapshot fed by the router (spec §5.2, design D-1).

No component in the tree retains a current-state snapshot (the router is a stateless
pump), so the console builds one here: a :class:`SnapshotStore` subscribes via
``Router.subscribe``/``Node.on_message`` and upserts

* PLI envelopes into *tracks*, keyed by ``source_uid``;
* MARKER envelopes into *detections*, keyed by the composite
  ``(source_uid, detection.track_id)`` — ``track_id`` is per-source tracker numbering and
  nullable (:class:`meshsa.models.Detection`), so it is neither globally unique nor always
  present; ``msg_id`` is the fallback key.

Bounds: per-kind caps with oldest-first eviction plus TTL staleness swept **on read** with
the injected :class:`meshsa.protocols.Clock` (no background task — staleness is bounded by
the page's poll cadence, and the sweep is deterministic under a fake clock). Handlers run
on the router's pump loop and the aiohttp handlers on the same event loop, so state
transitions are single-threaded: no locks.

Forward compatibility (spec §6): unknown *scalar* payload keys pass through to GeoJSON
``properties`` (the M3 additive-optional pattern); non-scalar unknowns are ignored and
counted, never rendered and never fatal.
"""

from __future__ import annotations

import collections
from dataclasses import dataclass
from typing import Any

import structlog

from ..models import Envelope, MessageKind
from ..protocols import Clock

_log = structlog.get_logger("meshsa.ui.snapshot")

__all__ = ["SnapshotStore"]

#: JSON-safe scalar types allowed to pass through into GeoJSON properties.
_SCALAR_TYPES = (str, int, float, bool)

#: Payload keys consumed structurally (never passed through as unknown keys).
_KNOWN_TOP_LEVEL = frozenset({"node", "position", "telemetry", "detection"})

#: Position keys consumed by the geometry (everything else in the block passes through).
_GEOMETRY_KEYS = frozenset({"lat", "lon"})


def _is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, _SCALAR_TYPES)


@dataclass
class _Entry:
    """One live track/detection: ingest recency + a pre-rendered GeoJSON feature."""

    seen_at: float
    feature: dict[str, Any]


class SnapshotStore:
    """Bounded, TTL-evicted current tactical picture (satisfies ``SnapshotSource``).

    ``handle`` is the router-subscriber (synchronous — the router awaits nothing for a
    sync handler and a failing subscriber never crashes the pump). ``tracks_geojson`` /
    ``detections_geojson`` are the pure renders, sweeping stale entries first.
    """

    def __init__(
        self,
        clock: Clock,
        *,
        max_tracks: int,
        max_detections: int,
        track_stale_s: float,
        detection_stale_s: float,
    ) -> None:
        if max_tracks <= 0 or max_detections <= 0:
            raise ValueError("snapshot caps must be > 0")
        if track_stale_s <= 0 or detection_stale_s <= 0:
            raise ValueError("snapshot TTLs must be > 0")
        self._clock = clock
        self._max_tracks = max_tracks
        self._max_detections = max_detections
        self._track_stale_s = track_stale_s
        self._detection_stale_s = detection_stale_s
        self._tracks: collections.OrderedDict[str, _Entry] = collections.OrderedDict()
        self._detections: collections.OrderedDict[str, _Entry] = collections.OrderedDict()
        # Observability of the bound (surfaced via /api/health, spec §5.2).
        self._counters: dict[str, int] = {
            "tracks_evicted": 0,
            "detections_evicted": 0,
            "tracks_expired": 0,
            "detections_expired": 0,
            "dropped_invalid": 0,
            "ignored_nonscalar_keys": 0,
        }

    # ── ingest (router subscriber) ────────────────────────────────────────────

    def handle(self, envelope: Envelope) -> None:
        """Upsert ``envelope`` into the picture; CHAT/STATUS are ignored in v1 (spec §4)."""
        if envelope.kind is MessageKind.PLI:
            self._upsert(
                self._tracks,
                key=envelope.source_uid,
                envelope=envelope,
                cap=self._max_tracks,
                evicted_counter="tracks_evicted",
            )
        elif envelope.kind is MessageKind.MARKER:
            self._upsert(
                self._detections,
                key=self._detection_key(envelope),
                envelope=envelope,
                cap=self._max_detections,
                evicted_counter="detections_evicted",
            )

    @staticmethod
    def _detection_key(envelope: Envelope) -> str:
        """Composite ``(source_uid, track_id)`` key; ``msg_id`` when ``track_id`` is absent.

        ``track_id`` alone is per-source tracker numbering, so two nodes may both emit
        ``track_id=1`` — the composite keeps them distinct (design D-1).
        """
        detection = envelope.payload.get("detection")
        track_id = detection.get("track_id") if isinstance(detection, dict) else None
        if track_id is None:
            return envelope.msg_id
        return f"{envelope.source_uid}:{track_id}"

    def _upsert(
        self,
        entries: collections.OrderedDict[str, _Entry],
        *,
        key: str,
        envelope: Envelope,
        cap: int,
        evicted_counter: str,
    ) -> None:
        feature = self._render_feature(envelope)
        if feature is None:
            self._counters["dropped_invalid"] += 1
            _log.warning(
                "ui_snapshot_dropped_invalid",
                kind=envelope.kind.value,
                source_uid=envelope.source_uid,
                msg_id=envelope.msg_id,
            )
            return
        entries[key] = _Entry(seen_at=self._clock.now(), feature=feature)
        entries.move_to_end(key)  # upsert refreshes recency: oldest-first eviction order
        while len(entries) > cap:
            entries.popitem(last=False)
            self._counters[evicted_counter] += 1

    def _render_feature(self, envelope: Envelope) -> dict[str, Any] | None:
        """Envelope -> GeoJSON Feature (pure). ``None`` when there is no usable position."""
        payload = envelope.payload
        position = payload.get("position")
        if not isinstance(position, dict):
            return None
        lat, lon = position.get("lat"), position.get("lon")
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            return None
        properties: dict[str, Any] = {
            "uid": envelope.source_uid,
            "ts": envelope.ts,
            "kind": envelope.kind.value,
        }
        node = payload.get("node")
        if isinstance(node, dict) and _is_scalar(node.get("callsign")):
            properties["callsign"] = node.get("callsign")
        # Position scalars beyond the geometry (hae/ce/le + M3 additive keys) pass through.
        self._merge_scalars(properties, position, skip=_GEOMETRY_KEYS)
        detection = payload.get("detection")
        if isinstance(detection, dict):
            self._merge_scalars(properties, detection)
        telemetry = payload.get("telemetry")
        if isinstance(telemetry, dict):
            self._merge_scalars(properties, telemetry, prefix="telemetry_")
        # Unknown top-level scalar keys pass through unchanged (spec §6 forward-compat).
        for key, value in payload.items():
            if key in _KNOWN_TOP_LEVEL:
                continue
            if _is_scalar(value):
                properties.setdefault(key, value)
            else:
                self._counters["ignored_nonscalar_keys"] += 1
        return {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [float(lon), float(lat)]},
            "properties": properties,
        }

    def _merge_scalars(
        self,
        properties: dict[str, Any],
        block: dict[str, Any],
        *,
        skip: frozenset[str] = frozenset(),
        prefix: str = "",
    ) -> None:
        """Copy a block's scalar values into ``properties``; count (never render) the rest."""
        for key, value in block.items():
            if key in skip:
                continue
            if _is_scalar(value):
                properties.setdefault(f"{prefix}{key}", value)
            else:
                self._counters["ignored_nonscalar_keys"] += 1

    # ── reads (pure renders; sweep first) ─────────────────────────────────────

    def tracks_geojson(self) -> dict[str, Any]:
        """Current live tracks as a GeoJSON ``FeatureCollection``."""
        self._sweep(self._tracks, self._track_stale_s, "tracks_expired")
        return _collection(self._tracks)

    def detections_geojson(self) -> dict[str, Any]:
        """Current live detections as a GeoJSON ``FeatureCollection``."""
        self._sweep(self._detections, self._detection_stale_s, "detections_expired")
        return _collection(self._detections)

    def counters(self) -> dict[str, int]:
        """Bound/drop observability (served by ``/api/health``); includes live sizes."""
        return {
            **self._counters,
            "tracks_live": len(self._tracks),
            "detections_live": len(self._detections),
        }

    def _sweep(
        self,
        entries: collections.OrderedDict[str, _Entry],
        stale_s: float,
        expired_counter: str,
    ) -> None:
        deadline = self._clock.now() - stale_s
        stale = [key for key, entry in entries.items() if entry.seen_at < deadline]
        for key in stale:
            del entries[key]
        self._counters[expired_counter] += len(stale)


def _collection(entries: collections.OrderedDict[str, _Entry]) -> dict[str, Any]:
    return {
        "type": "FeatureCollection",
        "features": [entry.feature for entry in entries.values()],
    }
