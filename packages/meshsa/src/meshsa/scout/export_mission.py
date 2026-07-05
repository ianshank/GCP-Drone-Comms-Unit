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


def to_ardupilot_waypoints(waypoints: Sequence[Waypoint]) -> str:
    """Build an ArduPilot/QGC WPL 110 ``.waypoints`` text block.

    Row 0 is the home/current item; each waypoint is a ``NAV_WAYPOINT`` in a relative-alt
    frame. Tab-separated per the QGC WPL spec.
    """
    lines = [_WPL_HEADER]
    for i, wp in enumerate(waypoints):
        current = 1 if i == 0 else 0
        lines.append(
            "\t".join(
                str(x)
                for x in (
                    wp.seq,
                    current,
                    _MAV_FRAME_GLOBAL_RELATIVE_ALT,
                    _MAV_CMD_NAV_WAYPOINT,
                    0,
                    0,
                    0,
                    0,
                    f"{wp.lat:.8f}",
                    f"{wp.lon:.8f}",
                    f"{wp.alt_agl_m:.2f}",
                    1,
                )
            )
        )
    return "\n".join(lines) + "\n"
