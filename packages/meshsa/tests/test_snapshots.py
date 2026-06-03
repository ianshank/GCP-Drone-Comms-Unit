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
