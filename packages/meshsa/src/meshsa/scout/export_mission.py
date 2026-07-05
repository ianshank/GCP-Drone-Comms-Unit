"""Offline survey export to QGC ``.plan`` and ArduPilot ``.waypoints`` (spec §1 Scout.3).

**Governance:** ratified under the CHARTER §3 offline-survey carve-out (2026-07-05). These
functions produce **inert files a human pilot reviews and loads** into their own GCS — scout
never uploads a mission, arms, or commands the vehicle. No autonomy, no auto-upload, no BVLOS.

Both emitters are pure (waypoints -> serialisable structure/string); file writing is left to
the CLI so the format logic stays fully unit-testable.
"""

from __future__ import annotations

from collections.abc import Sequence

from .schemas import Waypoint

#: MAV_CMD_NAV_WAYPOINT.
_MAV_CMD_NAV_WAYPOINT = 16
#: MAV_FRAME_GLOBAL_RELATIVE_ALT.
_MAV_FRAME_GLOBAL_RELATIVE_ALT = 3
#: MAV_FRAME_GLOBAL (absolute alt) — used for the WPL home row.
_MAV_FRAME_GLOBAL = 0
#: QGC waypoint-list text header.
_WPL_HEADER = "QGC WPL 110"


def to_qgc_plan(
    waypoints: Sequence[Waypoint],
    *,
    home: tuple[float, float, float] | None = None,
    cruise_speed_ms: float = 10.0,
    hover_speed_ms: float = 5.0,
) -> dict[str, object]:
    """Build a QGroundControl ``.plan`` structure (fileType ``Plan``, mission version 2)."""
    if home is None:
        first = waypoints[0] if waypoints else None
        home = (first.lat, first.lon, first.alt_agl_m) if first is not None else (0.0, 0.0, 0.0)
    items = [
        {
            "type": "SimpleItem",
            "command": _MAV_CMD_NAV_WAYPOINT,
            "frame": _MAV_FRAME_GLOBAL_RELATIVE_ALT,
            "params": [0, 0, 0, None, wp.lat, wp.lon, wp.alt_agl_m],
            "autoContinue": True,
            "doJumpId": wp.seq + 1,
            "Altitude": wp.alt_agl_m,
            "AltitudeMode": 1,
        }
        for wp in waypoints
    ]
    return {
        "fileType": "Plan",
        "version": 1,
        "groundStation": "meshsa-scout",
        "geoFence": {"circles": [], "polygons": [], "version": 2},
        "rallyPoints": {"points": [], "version": 2},
        "mission": {
            "version": 2,
            "firmwareType": 12,  # ArduPilot
            "vehicleType": 2,  # multirotor
            "cruiseSpeed": cruise_speed_ms,
            "hoverSpeed": hover_speed_ms,
            "globalPlanAltitudeMode": 1,
            "plannedHomePosition": [home[0], home[1], home[2]],
            "items": items,
        },
    }


def to_ardupilot_waypoints(
    waypoints: Sequence[Waypoint], *, home: tuple[float, float, float] | None = None
) -> str:
    """Build an ArduPilot/QGC WPL 110 ``.waypoints`` text block.

    QGC WPL 110 treats **row 0 as the planned home position** (its de-facto convention), so an
    explicit home row is emitted first (``current=1``, absolute-alt frame), then the survey
    waypoints follow at sequence ``1..N`` in a relative-alt frame — otherwise a GCS would take
    the first survey waypoint as home and shift the mission. Tab-separated per the WPL spec.
    """
    if home is None:
        first = waypoints[0] if waypoints else None
        home = (first.lat, first.lon, first.alt_agl_m) if first is not None else (0.0, 0.0, 0.0)
    rows: list[tuple[int, int, float, float, float]] = [
        (_MAV_FRAME_GLOBAL, 1, home[0], home[1], home[2])  # seq 0 = home / current
    ]
    for wp in waypoints:
        rows.append((_MAV_FRAME_GLOBAL_RELATIVE_ALT, 0, wp.lat, wp.lon, wp.alt_agl_m))
    lines = [_WPL_HEADER]
    for seq, (frame, current, lat, lon, alt) in enumerate(rows):
        lines.append(
            "\t".join(
                str(x)
                for x in (
                    seq,
                    current,
                    frame,
                    _MAV_CMD_NAV_WAYPOINT,
                    0,
                    0,
                    0,
                    0,
                    f"{lat:.8f}",
                    f"{lon:.8f}",
                    f"{alt:.2f}",
                    1,
                )
            )
        )
    return "\n".join(lines) + "\n"
