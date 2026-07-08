import math

import pytest

from jetson_yolo_gcs.geometry.ned import CameraFov, project_pixel_to_ned

CAM = CameraFov(img_w=640, img_h=480, h_fov_rad=1.204, v_fov_rad=0.733)


def test_nadir_center_is_directly_below():
    off = project_pixel_to_ned(CAM, 320, 240, alt_agl_m=100.0, heading_deg=0.0, pitch_deg=90.0)
    assert off is not None
    assert off.north_m == pytest.approx(0.0, abs=1e-6)
    assert off.east_m == pytest.approx(0.0, abs=1e-6)
    assert off.down_m == pytest.approx(100.0, abs=1e-6)


def test_forty_five_deg_depression_ranges_one_altitude_north():
    off = project_pixel_to_ned(CAM, 320, 240, alt_agl_m=100.0, heading_deg=0.0, pitch_deg=45.0)
    assert off is not None
    assert off.north_m == pytest.approx(100.0, rel=1e-6)
    assert off.east_m == pytest.approx(0.0, abs=1e-6)


def test_heading_rotates_offset_into_east():
    off = project_pixel_to_ned(CAM, 320, 240, alt_agl_m=100.0, heading_deg=90.0, pitch_deg=45.0)
    assert off is not None
    assert off.north_m == pytest.approx(0.0, abs=1e-6)
    assert off.east_m == pytest.approx(100.0, rel=1e-6)


def test_returns_none_at_or_above_horizon():
    assert (
        project_pixel_to_ned(CAM, 320, 240, alt_agl_m=100.0, heading_deg=0.0, pitch_deg=0.0) is None
    )


def test_returns_none_without_altitude():
    assert (
        project_pixel_to_ned(CAM, 320, 240, alt_agl_m=0.0, heading_deg=0.0, pitch_deg=90.0) is None
    )


def test_below_center_pixel_at_nadir_reflects_to_opposite_azimuth():
    """cy at the bottom image edge with pitch_deg=90 (nadir) pushes depression past 90 deg,
    i.e. the ray points behind the vehicle. The module reflects it onto the complementary
    depression at azimuth+180, so the hit lands *behind* (negative north for heading=0)
    rather than producing a meaningless negative range."""
    off = project_pixel_to_ned(CAM, 320, 480, alt_agl_m=100.0, heading_deg=0.0, pitch_deg=90.0)
    assert off is not None
    assert off.north_m == pytest.approx(-38.38420715383326, rel=1e-6)
    assert off.east_m == pytest.approx(0.0, abs=1e-6)
    assert off.down_m == pytest.approx(100.0, abs=1e-6)


def test_roll_rotates_angular_offset_about_optical_axis():
    """cx off-center (yaw_off != 0) with cy exactly on the centre row (pitch_off == 0 before
    roll) isolates the roll rotation: a 45 deg roll splits the pure yaw offset evenly into
    yaw/pitch components (cos(45)==sin(45)), giving north == east - yaw_off * cos(45 deg)
    contribution added to both the heading direction and the depression."""
    yaw_off_deg = math.degrees(
        math.atan(((2.0 * 400 / CAM.img_w) - 1.0) * math.tan(CAM.h_fov_rad / 2.0))
    )
    rotated = yaw_off_deg * math.cos(math.radians(45.0))
    depression_deg = 45.0 + rotated
    azimuth_deg = rotated
    expected_range = 100.0 / math.tan(math.radians(depression_deg))
    expected_north = expected_range * math.cos(math.radians(azimuth_deg))
    expected_east = expected_range * math.sin(math.radians(azimuth_deg))

    off = project_pixel_to_ned(
        CAM, 400, 240, alt_agl_m=100.0, heading_deg=0.0, pitch_deg=45.0, roll_deg=45.0
    )
    assert off is not None
    assert off.north_m == pytest.approx(expected_north, rel=1e-6)
    assert off.east_m == pytest.approx(expected_east, rel=1e-6)
    assert off.down_m == pytest.approx(100.0, abs=1e-6)


def test_roll_and_reflection_compose_for_below_center_pixel_at_nadir():
    """Exercises the roll rotation AND the depression>90 reflection TOGETHER — each is covered
    alone above, but a bug in their *composition* (e.g. reflecting before rolling, or dropping
    roll on the reflected path) would only surface here. Expected values are re-derived from
    first principles in the module's own order (angle-off-axis -> roll -> reflect -> range),
    not by calling the module twice, and a guard asserts the reflection branch really fires."""
    alt, heading, pitch, roll = 100.0, 0.0, 90.0, 45.0
    cx, cy = 320.0, 480.0  # centre column, bottom edge -> pre-roll depression > 90 (reflects)
    yaw = math.degrees(math.atan(((2.0 * cx / CAM.img_w) - 1.0) * math.tan(CAM.h_fov_rad / 2.0)))
    pit = math.degrees(math.atan(((2.0 * cy / CAM.img_h) - 1.0) * math.tan(CAM.v_fov_rad / 2.0)))
    r = math.radians(roll)
    yaw, pit = yaw * math.cos(r) - pit * math.sin(r), yaw * math.sin(r) + pit * math.cos(r)
    depression_deg = pitch + pit
    azimuth_deg = (heading + yaw) % 360.0
    assert depression_deg > 90.0  # guard: this pixel+roll genuinely triggers the reflection
    depression_deg, azimuth_deg = 180.0 - depression_deg, (azimuth_deg + 180.0) % 360.0
    expected_range = alt / math.tan(math.radians(depression_deg))

    off = project_pixel_to_ned(
        CAM, cx, cy, alt_agl_m=alt, heading_deg=heading, pitch_deg=pitch, roll_deg=roll
    )
    assert off is not None
    assert off.north_m == pytest.approx(expected_range * math.cos(math.radians(azimuth_deg)))
    assert off.east_m == pytest.approx(expected_range * math.sin(math.radians(azimuth_deg)))
    assert off.down_m == pytest.approx(alt)
