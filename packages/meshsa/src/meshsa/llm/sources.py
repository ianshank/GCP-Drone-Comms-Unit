"""Read-only data sources for the situational-awareness (SA) assistant.

The LLM never touches a radio, autopilot, or TAK server directly. It reads a
small, typed snapshot of vehicle and track state through the ``TelemetrySource``
and ``TrackSource`` protocols. This keeps the assistant **advisory and
read-only**: nothing here can arm a vehicle, change a flight mode, or publish a
CoT track.

Concrete HTTP sources (``Mavlink2RestSource``, ``FtsTrackSource``) lazy-import
their HTTP client, so importing this module never requires the ``[llm]`` extra.
The wire-parsing logic is split into pure functions (``parse_global_position_int``,
``parse_fts_tracks``) that are unit-tested without a network; tests inject the
in-memory ``Static*`` sources.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any, Protocol

from pydantic import BaseModel

# GLOBAL_POSITION_INT field scaling (see MAVLink common message set).
_DEGE7 = 1e7  # lat/lon: degrees * 1e7
_MM_PER_M = 1000.0  # alt/relative_alt: millimeters
_CM_PER_M = 100.0  # vx/vy: centimeters per second
_CDEG = 100.0  # hdg: centidegrees
_HDG_UNKNOWN = 65535  # MAVLink sentinel for "heading not available"


class DroneState(BaseModel):
    """A point-in-time snapshot of one vehicle's telemetry.

    Every numeric field is optional: a source that cannot observe a value (no
    GPS fix, no battery telemetry) leaves it ``None`` rather than guessing.
    """

    uid: str
    lat: float | None = None
    lon: float | None = None
    alt_m: float | None = None
    relative_alt_m: float | None = None
    ground_speed_ms: float | None = None
    heading_deg: float | None = None
    battery_pct: float | None = None
    armed: bool | None = None
    mode: str | None = None
    link_ok: bool = True


class Track(BaseModel):
    """A single CoT/ATAK track as seen on the TAK network."""

    uid: str
    callsign: str | None = None
    cot_type: str | None = None
    lat: float | None = None
    lon: float | None = None
    stale_s: float | None = None


class TelemetrySource(Protocol):
    """Async read of the current vehicle telemetry snapshot."""

    async def drone_state(self) -> DroneState: ...


class TrackSource(Protocol):
    """Async read of the current TAK track list."""

    async def tracks(self) -> list[Track]: ...


class StaticTelemetrySource:
    """In-memory ``TelemetrySource`` for tests, the simulator, and demos."""

    def __init__(self, state: DroneState) -> None:
        self._state = state

    def set_state(self, state: DroneState) -> None:
        self._state = state

    async def drone_state(self) -> DroneState:
        return self._state


class StaticTrackSource:
    """In-memory ``TrackSource`` for tests, the simulator, and demos."""

    def __init__(self, tracks: list[Track] | None = None) -> None:
        self._tracks = list(tracks or [])

    def set_tracks(self, tracks: list[Track]) -> None:
        self._tracks = list(tracks)

    async def tracks(self) -> list[Track]:
        return list(self._tracks)


def _as_float(value: Any) -> float | None:
    """Best-effort numeric coercion; non-numeric or missing values become None.

    Accepts numeric strings (some JSON APIs send numbers as strings to avoid
    precision loss); ``bool`` is rejected so ``True``/``False`` are never read as
    ``1``/``0``.
    """
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _first_present(row: Mapping[str, Any], *keys: str) -> Any:
    """First value among ``keys`` that is present and not ``None`` (0/0.0-safe)."""
    for key in keys:
        value = row.get(key)
        if value is not None:
            return value
    return None


def parse_global_position_int(payload: Mapping[str, Any], uid: str) -> DroneState:
    """Map a mavlink2rest ``GLOBAL_POSITION_INT`` message to a ``DroneState``.

    Pure: accepts either the raw message dict or a ``{"message": {...}}``
    envelope (mavlink2rest wraps messages), applies the documented MAVLink field
    scaling, and treats the ``65535`` heading sentinel as "unknown".
    """
    msg = payload.get("message", payload)
    lat_raw = _as_float(msg.get("lat"))
    lon_raw = _as_float(msg.get("lon"))
    alt_raw = _as_float(msg.get("alt"))
    rel_raw = _as_float(msg.get("relative_alt"))
    vx = _as_float(msg.get("vx"))
    vy = _as_float(msg.get("vy"))
    hdg_raw = _as_float(msg.get("hdg"))

    ground_speed = None
    if vx is not None and vy is not None:
        ground_speed = math.hypot(vx, vy) / _CM_PER_M

    heading = None
    if hdg_raw is not None and hdg_raw != _HDG_UNKNOWN:
        heading = hdg_raw / _CDEG

    return DroneState(
        uid=uid,
        lat=lat_raw / _DEGE7 if lat_raw is not None else None,
        lon=lon_raw / _DEGE7 if lon_raw is not None else None,
        alt_m=alt_raw / _MM_PER_M if alt_raw is not None else None,
        relative_alt_m=rel_raw / _MM_PER_M if rel_raw is not None else None,
        ground_speed_ms=ground_speed,
        heading_deg=heading,
    )


def parse_fts_tracks(data: Any) -> list[Track]:
    """Map a FreeTAKServer active-CoT payload to ``Track`` objects (pure).

    Tolerant of the common shapes FTS/WebMap return: a top-level list, or a dict
    wrapping the list under ``results``/``data``/``rows``. Each entry's lat/lon,
    callsign, type, and uid are read from any of the field aliases seen in the
    wild; unparseable entries are skipped rather than raising.
    """
    rows: list[Any]
    if isinstance(data, Mapping):
        for key in ("results", "data", "rows", "geoObjects"):
            inner = data.get(key)
            if isinstance(inner, list):
                rows = inner
                break
        else:
            rows = []
    elif isinstance(data, list):
        rows = data
    else:
        rows = []

    tracks: list[Track] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        uid = row.get("uid") or row.get("id") or row.get("name")
        if uid is None:
            continue
        tracks.append(
            Track(
                uid=str(uid),
                callsign=_first_str(row, "callsign", "name", "detail_callsign"),
                cot_type=_first_str(row, "cot_type", "type", "how"),
                # None-aware field selection: a valid 0.0 lat/lon (equator /
                # prime meridian) or stale of 0 must not fall through to the alias.
                lat=_as_float(_first_present(row, "lat", "latitude")),
                lon=_as_float(_first_present(row, "lon", "longitude")),
                stale_s=_as_float(_first_present(row, "stale_s", "stale")),
            )
        )
    return tracks


def _first_str(row: Mapping[str, Any], *keys: str) -> str | None:
    """First non-empty value among ``keys``, stringified (numeric labels allowed)."""
    for key in keys:
        value = row.get(key)
        if value is None or isinstance(value, bool):
            continue
        text = str(value).strip()
        if text:
            return text
    return None


class Mavlink2RestSource:  # pragma: no cover - real HTTP I/O
    """``TelemetrySource`` backed by a running mavlink2rest server.

    ``aiohttp`` is imported inside the method so importing this module never
    requires the ``[llm]`` extra. Parsing is delegated to the unit-tested
    ``parse_global_position_int``.
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8088",
        *,
        uid: str = "uav-1",
        vehicle_id: int = 1,
        component_id: int = 1,
        timeout_s: float = 3.0,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._uid = uid
        self._vehicle_id = vehicle_id
        self._component_id = component_id
        self._timeout_s = timeout_s

    async def drone_state(self) -> DroneState:
        import aiohttp

        url = (
            f"{self._base}/v1/mavlink/vehicles/{self._vehicle_id}"
            f"/components/{self._component_id}/messages/GLOBAL_POSITION_INT"
        )
        timeout = aiohttp.ClientTimeout(total=self._timeout_s)
        try:
            async with (
                aiohttp.ClientSession(timeout=timeout) as session,
                session.get(url) as resp,
            ):
                resp.raise_for_status()
                payload = await resp.json()
        except Exception:
            return DroneState(uid=self._uid, link_ok=False)
        return parse_global_position_int(payload, self._uid)


class FtsTrackSource:  # pragma: no cover - real HTTP I/O
    """``TrackSource`` backed by a FreeTAKServer REST endpoint."""

    def __init__(
        self,
        url: str = "http://127.0.0.1:19023/ManageGeoObject/getCoTGeoObject",
        *,
        timeout_s: float = 3.0,
    ) -> None:
        self._url = url
        self._timeout_s = timeout_s

    async def tracks(self) -> list[Track]:
        import aiohttp

        timeout = aiohttp.ClientTimeout(total=self._timeout_s)
        try:
            async with (
                aiohttp.ClientSession(timeout=timeout) as session,
                session.get(self._url) as resp,
            ):
                resp.raise_for_status()
                data = await resp.json()
        except Exception:
            return []
        return parse_fts_tracks(data)
