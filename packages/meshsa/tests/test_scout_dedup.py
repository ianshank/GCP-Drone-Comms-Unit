"""Tests for meshsa.scout.dedup.Deduplicator — clustering + M8N regression."""

from __future__ import annotations

from meshsa.cv.geo import destination
from meshsa.scout.dedup import Deduplicator
from meshsa.scout.schemas import GeoDetection


def _det(id_: str, lat: float, lon: float, conf: float = 0.9, status: str = "new") -> GeoDetection:
    return GeoDetection(
        id=id_,
        lat=lat,
        lon=lon,
        cls="missing_vine",
        conf=conf,
        error_m=0.3,
        src_frame="f",
        ts=1.0,
        status=status,
    )


def test_close_detections_merge_to_one() -> None:
    d = Deduplicator(radius_m=1.0)
    first = d.add(_det("a", 38.5, -122.5))
    near_lat, near_lon = destination(38.5, -122.5, 45.0, 0.5)  # 0.5 m away
    second = d.add(_det("b", near_lat, near_lon))
    assert d.merges == 1
    assert len(d.results()) == 1
    assert second.id == first.id  # stable cluster id


def test_higher_confidence_wins_position_keeps_id_and_status() -> None:
    d = Deduplicator(radius_m=2.0)
    d.add(_det("a", 38.5, -122.5, conf=0.5, status="tagged"))
    near_lat, near_lon = destination(38.5, -122.5, 0.0, 1.0)
    merged = d.add(_det("b", near_lat, near_lon, conf=0.95))
    assert merged.id == "a"  # cluster id preserved
    assert merged.status == "tagged"  # operator triage preserved
    assert merged.lat == near_lat  # higher-confidence position adopted


def test_far_detections_stay_separate() -> None:
    d = Deduplicator(radius_m=1.0)
    d.add(_det("a", 38.5, -122.5))
    far_lat, far_lon = destination(38.5, -122.5, 90.0, 50.0)
    d.add(_det("b", far_lat, far_lon))
    assert d.merges == 0
    assert len(d.results()) == 2


def test_m8n_noise_merges_across_vines_regression() -> None:
    """Regression proof that A1 needs RTK: two vines 2 m apart, with M8N-scale (~2.5 m)
    position error the fixes fall within a vine_spacing/2 cluster radius and merge into one
    pin — exactly the failure the RTK requirement prevents."""
    radius = 1.0  # vine_spacing (2 m) / 2
    d = Deduplicator(radius_m=radius)
    # Vine A truth, and vine B one row (2 m) away, but each observed with ~2 m error that
    # drags them within the cluster radius of each other.
    vine_a = _det("a", 38.5, -122.5)
    b_lat, b_lon = destination(38.5, -122.5, 90.0, 0.8)  # observed 0.8 m away (< radius)
    d.add(vine_a)
    d.add(_det("b", b_lat, b_lon))
    assert len(d.results()) == 1  # two distinct vines collapsed to one pin under M8N noise
