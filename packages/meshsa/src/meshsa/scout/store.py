"""Persistence + grower-facing exports for georeferenced detections (Scout.2/Scout.4).

``InMemoryStore`` and ``SqliteStore`` both satisfy :class:`~meshsa.scout.protocols.Store`;
the SQLite backend uses only the standard-library ``sqlite3`` (no new dependency) and
accepts ``":memory:"`` or a file path. ``to_geojson`` / ``to_csv`` are pure exporters for
the ``/export.*`` endpoints and the CLI.
"""

from __future__ import annotations

import csv
import io
import sqlite3
from collections.abc import Iterable

import structlog

from .schemas import GeoDetection

_log = structlog.get_logger("meshsa.scout.store")

#: Column order shared by the SQLite schema and the CSV export.
_FIELDS = ("id", "lat", "lon", "cls", "conf", "error_m", "src_frame", "ts", "status", "block_id")
#: ``store_path`` sentinel selecting the volatile in-memory backend.
_MEMORY = ":memory:"


class InMemoryStore:
    """Dict-backed store — the default for tests and single-session runs."""

    def __init__(self) -> None:
        self._by_id: dict[str, GeoDetection] = {}

    def add(self, detection: GeoDetection) -> None:
        self._by_id[detection.id] = detection

    def get(self, detection_id: str) -> GeoDetection | None:
        return self._by_id.get(detection_id)

    def all(self) -> list[GeoDetection]:
        return list(self._by_id.values())

    def by_block(self, block_id: str) -> list[GeoDetection]:
        return [d for d in self._by_id.values() if d.block_id == block_id]

    def set_status(self, detection_id: str, status: str) -> GeoDetection | None:
        current = self._by_id.get(detection_id)
        if current is None:
            return None
        updated = current.with_status(status)  # validates status
        self._by_id[detection_id] = updated
        return updated


class SqliteStore:
    """SQLite-backed store (stdlib ``sqlite3``); ``path`` may be ``":memory:"``."""

    def __init__(self, path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS detections ("
            "id TEXT PRIMARY KEY, lat REAL, lon REAL, cls TEXT, conf REAL, "
            "error_m REAL, src_frame TEXT, ts REAL, status TEXT, block_id TEXT)"
        )
        self._conn.commit()

    def add(self, detection: GeoDetection) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO detections "
            "(id, lat, lon, cls, conf, error_m, src_frame, ts, status, block_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                detection.id,
                detection.lat,
                detection.lon,
                detection.cls,
                detection.conf,
                detection.error_m,
                detection.src_frame,
                detection.ts,
                detection.status,
                detection.block_id,
            ),
        )
        self._conn.commit()

    def _row_to_detection(self, row: sqlite3.Row) -> GeoDetection:
        return GeoDetection(**{k: row[k] for k in _FIELDS})

    def get(self, detection_id: str) -> GeoDetection | None:
        cur = self._conn.execute("SELECT * FROM detections WHERE id = ?", (detection_id,))
        row = cur.fetchone()
        return self._row_to_detection(row) if row is not None else None

    def all(self) -> list[GeoDetection]:
        cur = self._conn.execute("SELECT * FROM detections ORDER BY ts")
        return [self._row_to_detection(r) for r in cur.fetchall()]

    def by_block(self, block_id: str) -> list[GeoDetection]:
        cur = self._conn.execute(
            "SELECT * FROM detections WHERE block_id = ? ORDER BY ts", (block_id,)
        )
        return [self._row_to_detection(r) for r in cur.fetchall()]

    def set_status(self, detection_id: str, status: str) -> GeoDetection | None:
        current = self.get(detection_id)
        if current is None:
            return None
        updated = current.with_status(status)  # validates status
        self.add(updated)
        return updated

    def close(self) -> None:
        self._conn.close()


def build_store(store_path: str) -> InMemoryStore | SqliteStore:
    """Select a store from config: a file-backed :class:`SqliteStore` for a real path, else the
    volatile :class:`InMemoryStore` (``":memory:"``, the default)."""
    if store_path and store_path != _MEMORY:
        _log.info("store_sqlite", path=store_path)
        return SqliteStore(store_path)
    return InMemoryStore()


def to_geojson(detections: Iterable[GeoDetection]) -> dict[str, object]:
    """Serialise detections to a GeoJSON ``FeatureCollection`` (lon, lat order)."""
    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [d.lon, d.lat]},
            "properties": {
                "id": d.id,
                "cls": d.cls,
                "conf": d.conf,
                "error_m": d.error_m,
                "src_frame": d.src_frame,
                "ts": d.ts,
                "status": d.status,
                "block_id": d.block_id,
            },
        }
        for d in detections
    ]
    return {"type": "FeatureCollection", "features": features}


def to_csv(detections: Iterable[GeoDetection]) -> str:
    """Serialise detections to CSV with a header row (column order ``_FIELDS``)."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(_FIELDS)
    for d in detections:
        writer.writerow([getattr(d, f) for f in _FIELDS])
    return buf.getvalue()
