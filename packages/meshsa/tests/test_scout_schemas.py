"""Unit tests for meshsa.scout.schemas — validation + immutability."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from meshsa.scout.schemas import BBox, Block, GeoDetection, PixelDetection, Waypoint


def _geo(**over: object) -> GeoDetection:
    base: dict[str, object] = dict(
        id="d1",
        lat=38.5,
        lon=-122.5,
        cls="missing_vine",
        conf=0.9,
        error_m=0.5,
        src_frame="f0",
        ts=1.0,
    )
    base.update(over)
    return GeoDetection(**base)  # type: ignore[arg-type]


def test_bbox_center() -> None:
    b = BBox(x1=10, y1=20, x2=30, y2=60)
    assert b.cx == 20.0
    assert b.cy == 40.0


def test_bbox_rejects_non_finite() -> None:
    with pytest.raises(ValidationError):
        BBox(x1=float("nan"), y1=0, x2=1, y2=1)


def test_pixel_detection_conf_range() -> None:
    with pytest.raises(ValidationError):
        PixelDetection(frame_id="f", ts=1.0, bbox=BBox(x1=0, y1=0, x2=1, y2=1), cls="x", conf=1.5)
    with pytest.raises(ValidationError):
        PixelDetection(
            frame_id="f", ts=float("inf"), bbox=BBox(x1=0, y1=0, x2=1, y2=1), cls="x", conf=0.5
        )


def test_geodetection_valid_and_frozen() -> None:
    d = _geo()
    with pytest.raises(ValidationError):
        d.lat = 0.0  # type: ignore[misc]  # frozen


@pytest.mark.parametrize(
    "field,value",
    [("lat", 91.0), ("lon", 200.0), ("conf", 2.0), ("error_m", -1.0), ("status", "bogus")],
)
def test_geodetection_rejects_bad(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        _geo(**{field: value})


def test_geodetection_with_status_returns_copy() -> None:
    d = _geo()
    tagged = d.with_status("tagged")
    assert tagged.status == "tagged"
    assert d.status == "new"  # original unchanged
    assert tagged.id == d.id


def test_block_validation() -> None:
    poly = [(38.5, -122.5), (38.5, -122.4), (38.6, -122.4)]
    b = Block(
        block_id="b",
        polygon=poly,
        row_azimuth_deg=10.0,
        mean_elev_m=60.0,
        vine_spacing_m=2.0,
        row_spacing_m=2.4,
    )
    assert len(b.polygon) == 3
    with pytest.raises(ValidationError):  # too few vertices
        Block(
            block_id="b",
            polygon=[(0, 0), (1, 1)],
            row_azimuth_deg=0.0,
            mean_elev_m=0.0,
            vine_spacing_m=1.0,
            row_spacing_m=1.0,
        )
    with pytest.raises(ValidationError):  # azimuth out of range
        Block(
            block_id="b",
            polygon=poly,
            row_azimuth_deg=360.0,
            mean_elev_m=0.0,
            vine_spacing_m=1.0,
            row_spacing_m=1.0,
        )
    with pytest.raises(ValidationError):  # non-positive spacing
        Block(
            block_id="b",
            polygon=poly,
            row_azimuth_deg=0.0,
            mean_elev_m=0.0,
            vine_spacing_m=0.0,
            row_spacing_m=1.0,
        )
    with pytest.raises(ValidationError):  # polygon lat out of range
        Block(
            block_id="b",
            polygon=[(91.0, 0.0), (0.0, 0.0), (1.0, 1.0)],
            row_azimuth_deg=0.0,
            mean_elev_m=0.0,
            vine_spacing_m=1.0,
            row_spacing_m=1.0,
        )


def test_waypoint_validation() -> None:
    w = Waypoint(seq=0, lat=38.5, lon=-122.5, alt_agl_m=60.0)
    assert w.seq == 0
    with pytest.raises(ValidationError):  # alt must be > 0
        Waypoint(seq=1, lat=0.0, lon=0.0, alt_agl_m=0.0)
    with pytest.raises(ValidationError):  # lat range
        Waypoint(seq=1, lat=91.0, lon=0.0, alt_agl_m=10.0)
