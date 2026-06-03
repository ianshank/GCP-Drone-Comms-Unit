import pytest
from pydantic import ValidationError

from meshsa import Envelope, MessageKind, NodeInfo, NodeTier, Position
from meshsa.version import SCHEMA_VERSION, is_compatible


def test_compatibility_window():
    assert is_compatible(SCHEMA_VERSION)
    assert not is_compatible(SCHEMA_VERSION + 1)
    assert not is_compatible(0)


def test_position_bounds_ok():
    p = Position(lat=45.0, lon=-120.0)
    assert p.hae == 0.0


@pytest.mark.parametrize("lat,lon", [(91, 0), (-91, 0), (0, 181), (0, -181)])
def test_position_bounds_reject(lat, lon):
    with pytest.raises(ValidationError):
        Position(lat=lat, lon=lon)


def test_envelope_defaults_schema_version():
    e = Envelope(msg_id="x", ts=1.0, source_uid="u", kind=MessageKind.PLI)
    assert e.schema_version == SCHEMA_VERSION
    assert e.payload == {}


def test_nodeinfo_default_tier():
    assert NodeInfo(uid="u", callsign="c").tier == NodeTier.USER


def test_default_clock_and_id_factory():
    from meshsa import SystemClock, UuidFactory

    assert SystemClock().now() > 0
    a, b = UuidFactory().new_id(), UuidFactory().new_id()
    assert a != b and len(a) == 32
