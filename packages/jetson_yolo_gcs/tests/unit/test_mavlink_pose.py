"""Injectable ``PoseSource`` seam: ATTITUDE + AGL reduce-to-``VehiclePose`` (fake conn)."""

from __future__ import annotations

import math

import pytest

from jetson_yolo_gcs.mavlink.pose import MavlinkPoseSource, PoseSource, VehiclePose


class _FakeAttitude:
    """Duck-typed pymavlink ATTITUDE (only the accessors the source reads)."""

    def __init__(self, roll: float, pitch: float, yaw: float) -> None:
        self.roll, self.pitch, self.yaw = roll, pitch, yaw

    def get_type(self) -> str:
        return "ATTITUDE"


class _FakeConn:
    """Queued-message fake: successive ``recv_match`` calls pop the inbox, then ``None``."""

    def __init__(self, msgs: list[object] | None = None) -> None:
        self._inbox: list[object] = list(msgs or [])
        self.recv_calls = 0

    def recv_match(self, *, type: str, blocking: bool) -> object | None:  # noqa: A002
        self.recv_calls += 1
        assert type == "ATTITUDE" and blocking is False
        return self._inbox.pop(0) if self._inbox else None


class _BoomConn:
    """A connection whose ``recv_match`` raises, exercising the swallow-and-return-False path."""

    def recv_match(self, *, type: str, blocking: bool) -> object:  # noqa: A002
        raise OSError("link read failed")


def test_pose_source_reduces_attitude_to_vehicle_pose() -> None:
    # camera fixed nadir-ish via config depression; here verify heading/roll mapping from ATTITUDE.
    src = MavlinkPoseSource(
        connection=_FakeConn(msgs=[_FakeAttitude(roll=0.0, pitch=0.0, yaw=math.pi / 2)]),
        camera_depression_deg=90.0,
        agl_source_m=lambda: 50.0,
    )
    assert src.poll() is True
    pose = src.latest()
    assert pose is not None
    assert pose.heading_deg == pytest.approx(90.0, abs=1e-6)
    assert pose.alt_agl_m == pytest.approx(50.0)
    assert pose.pitch_deg == pytest.approx(90.0)  # nadir camera depression from config
    assert pose.roll_deg == pytest.approx(0.0, abs=1e-6)


def test_pose_source_latest_none_before_first_poll() -> None:
    src = MavlinkPoseSource(
        connection=_FakeConn(msgs=[]), camera_depression_deg=90.0, agl_source_m=lambda: 50.0
    )
    assert src.latest() is None


def test_poll_returns_false_when_no_attitude_pending() -> None:
    # Empty inbox -> recv_match returns None -> poll is a no-op (still covers the fake's line).
    src = MavlinkPoseSource(
        connection=_FakeConn(msgs=[]), camera_depression_deg=90.0, agl_source_m=lambda: 50.0
    )
    assert src.poll() is False
    assert src.latest() is None


def test_poll_maps_nonzero_roll_to_degrees() -> None:
    src = MavlinkPoseSource(
        connection=_FakeConn(msgs=[_FakeAttitude(roll=math.pi / 4, pitch=0.0, yaw=0.0)]),
        camera_depression_deg=45.0,
        agl_source_m=lambda: 12.5,
    )
    assert src.poll() is True
    pose = src.latest()
    assert pose is not None
    assert pose.roll_deg == pytest.approx(45.0, abs=1e-6)
    assert pose.heading_deg == pytest.approx(0.0, abs=1e-6)
    assert pose.alt_agl_m == pytest.approx(12.5)


def test_poll_wraps_negative_yaw_into_0_360_heading() -> None:
    # yaw=-pi/2 rad = -90 deg -> heading must wrap to 270 deg, never negative.
    src = MavlinkPoseSource(
        connection=_FakeConn(msgs=[_FakeAttitude(roll=0.0, pitch=0.0, yaw=-math.pi / 2)]),
        camera_depression_deg=90.0,
        agl_source_m=lambda: 50.0,
    )
    assert src.poll() is True
    pose = src.latest()
    assert pose is not None
    assert pose.heading_deg == pytest.approx(270.0, abs=1e-6)


def test_poll_returns_false_and_keeps_stale_pose_when_agl_source_returns_none() -> None:
    # A missing AGL reading (e.g. rangefinder not yet valid) must not fabricate an altitude;
    # the previously cached pose (if any) must survive untouched.
    conn = _FakeConn(
        msgs=[
            _FakeAttitude(roll=0.0, pitch=0.0, yaw=0.0),
            _FakeAttitude(roll=0.0, pitch=0.0, yaw=math.pi),
        ]
    )
    agl_values = iter([50.0, None])
    src = MavlinkPoseSource(
        connection=conn, camera_depression_deg=90.0, agl_source_m=lambda: next(agl_values)
    )
    assert src.poll() is True
    first_pose = src.latest()
    assert first_pose is not None
    assert first_pose.heading_deg == pytest.approx(0.0, abs=1e-6)

    assert src.poll() is False  # second ATTITUDE drained, but AGL is None -> no update
    assert src.latest() is first_pose  # unchanged, same cached object


def test_poll_swallows_connection_error_and_returns_false() -> None:
    # A transient link error (e.g. serial hiccup) must never propagate out of poll().
    src = MavlinkPoseSource(
        connection=_BoomConn(), camera_depression_deg=90.0, agl_source_m=lambda: 50.0
    )
    assert src.poll() is False
    assert src.latest() is None


def test_mavlink_pose_source_satisfies_pose_source_protocol() -> None:
    src = MavlinkPoseSource(
        connection=_FakeConn(msgs=[]), camera_depression_deg=90.0, agl_source_m=lambda: 50.0
    )
    assert isinstance(src, PoseSource)


def test_vehicle_pose_is_frozen() -> None:
    pose = VehiclePose(alt_agl_m=1.0, heading_deg=2.0, pitch_deg=3.0)
    assert pose.roll_deg == 0.0  # default
    with pytest.raises(AttributeError):
        pose.alt_agl_m = 5.0  # type: ignore[misc]
