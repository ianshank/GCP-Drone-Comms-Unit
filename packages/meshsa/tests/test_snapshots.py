"""Serialized-envelope snapshot tests: catch accidental wire-format breakage.

Regenerate goldens with ``MESHSA_UPDATE_SNAPSHOTS=1 pytest tests/test_snapshots.py``.
All inputs are pinned (ts/msg_id/stale_s) so encodings are deterministic.
"""

import os
import pathlib

from meshsa import CompactCodec, CotCodec, Envelope, JsonCodec, MessageKind

_SNAP = pathlib.Path(__file__).parent / "snapshots"


def _canonical_pli():
    return Envelope(
        schema_version=1,
        msg_id="snap-1",
        ts=1_700_000_000.0,  # integer second -> CoT timestamps are stable
        source_uid="user-1",
        kind=MessageKind.PLI,
        payload={
            "node": {"uid": "user-1", "callsign": "FOX1", "tier": "user"},
            "position": {"lat": 37.5, "lon": -122.3, "hae": 12.0, "ce": 9999999.0, "le": 9999999.0},
        },
    )


def _canonical_rich_pli():
    # M3.1 richer track: course/speed + telemetry (battery/current/attitude).
    return Envelope(
        schema_version=1,
        msg_id="snap-rich-1",
        ts=1_700_000_000.0,
        source_uid="uav-1",
        kind=MessageKind.PLI,
        payload={
            "node": {"uid": "uav-1", "callsign": "UAV1", "tier": "user"},
            "position": {
                "lat": 37.5,
                "lon": -122.3,
                "hae": 12.0,
                "ce": 9999999.0,
                "le": 9999999.0,
                "course_deg": 270.0,
                "speed_ms": 8.5,
            },
            "telemetry": {
                "battery_v": 11.1,
                "battery_pct": 75,
                "current_a": 4.2,
                "attitude": {"roll_deg": 1.0, "pitch_deg": -2.0, "yaw_deg": 90.0},
            },
        },
    )


def _check(name: str, data: bytes) -> None:
    _SNAP.mkdir(exist_ok=True)
    path = _SNAP / name
    if os.environ.get("MESHSA_UPDATE_SNAPSHOTS"):  # pragma: no cover - dev regen path
        path.write_bytes(data)
        return
    assert data == path.read_bytes(), f"wire format for {name} changed"


def test_json_snapshot():
    _check("pli.json", JsonCodec().encode(_canonical_pli()))


def test_compact_snapshot():
    _check("pli.compact.bin", CompactCodec().encode(_canonical_pli()))


def test_cot_snapshot():
    _check("pli.cot.xml", CotCodec(stale_s=120.0).encode(_canonical_pli()))


def test_rich_json_snapshot():
    _check("pli_rich.json", JsonCodec().encode(_canonical_rich_pli()))


def test_rich_cot_snapshot():
    _check("pli_rich.cot.xml", CotCodec(stale_s=120.0).encode(_canonical_rich_pli()))
