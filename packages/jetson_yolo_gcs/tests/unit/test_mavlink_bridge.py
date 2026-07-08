"""LANDING_TARGET angle math + publish gating + send args (fake pymavlink conn)."""

from __future__ import annotations

import pytest
from structlog.testing import capture_logs

from jetson_yolo_gcs.core.config import MavlinkSettings
from jetson_yolo_gcs.core.errors import MavlinkError
from jetson_yolo_gcs.detection.base import Detection, DetectionResult
from jetson_yolo_gcs.mavlink.bridge import LandingTargetBridge, compute_angles
from jetson_yolo_gcs.mavlink.heartbeat import HeartbeatMonitor
from jetson_yolo_gcs.mavlink.pose import VehiclePose
from jetson_yolo_gcs.mavlink.timesync import TimeSync
from tests.conftest import FakeClock
from tests.unit.test_mavlink_heartbeat import SettableClock


class _FakeMav:
    def __init__(self) -> None:
        #: Each entry is ``(args, kwargs)`` for one ``landing_target_send`` call, so tests
        #: can pin both the positional arity/values *and* that no kwargs snuck in (the
        #: latter matters for the pre-NED-refactor characterization test below).
        self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def landing_target_send(self, *args: object, **kwargs: object) -> None:
        self.calls.append((args, kwargs))


class _FakeMsg:
    """Duck-typed pymavlink HEARTBEAT (only the accessors the bridge reads)."""

    def __init__(self, src_system: int = 1, src_component: int = 1) -> None:
        self._sys = src_system
        self._comp = src_component

    def get_srcSystem(self) -> int:  # noqa: N802 - pymavlink accessor name
        return self._sys

    def get_srcComponent(self) -> int:  # noqa: N802 - pymavlink accessor name
        return self._comp


class _FakeConn:
    def __init__(self, heartbeats: list[object] | None = None) -> None:
        self.mav = _FakeMav()
        self.closed = False
        #: Messages returned by successive ``recv_match`` calls, then ``None`` forever.
        self._inbox: list[object] = list(heartbeats or [])
        self.recv_calls = 0

    def recv_match(self, *, type: str, blocking: bool) -> object | None:  # noqa: A002
        self.recv_calls += 1
        assert type == "HEARTBEAT" and blocking is False
        return self._inbox.pop(0) if self._inbox else None

    def close(self) -> None:
        self.closed = True


def _fresh_monitor() -> HeartbeatMonitor:
    """A heartbeat monitor with a just-recorded, in-window beat (gate open)."""
    mon = HeartbeatMonitor(SettableClock(100.0), max_age_s=2.0)
    mon.beat(t=100.0)
    return mon


def _result_with(bbox: tuple[float, float, float, float]) -> tuple[Detection, DetectionResult]:
    det = Detection(class_id=0, class_name="pad", confidence=1.0, bbox=bbox)
    return det, DetectionResult(detections=(det,), width=200, height=200)


def test_compute_angles_centered_is_zero() -> None:
    det, result = _result_with((90, 90, 110, 110))  # centre (100,100) of 200x200
    ax, ay = compute_angles(det, result, fov_x_rad=1.0, fov_y_rad=1.0)
    assert ax == pytest.approx(0.0)
    assert ay == pytest.approx(0.0)


def test_compute_angles_right_of_centre_is_positive() -> None:
    det, result = _result_with((140, 90, 160, 110))  # centre x=150 -> +0.25 * fov
    ax, _ = compute_angles(det, result, fov_x_rad=2.0, fov_y_rad=2.0)
    assert ax == pytest.approx(0.5)


def test_publish_noop_when_disabled() -> None:
    conn = _FakeConn()
    bridge = LandingTargetBridge(MavlinkSettings(enable_landing_target=False), connection=conn)
    det, result = _result_with((90, 90, 110, 110))
    assert bridge.publish(det, result) is False
    assert conn.mav.calls == []


def test_publish_sends_landing_target_when_enabled() -> None:
    # Contract (2026-07): with the fail-closed gate on, a fresh heartbeat must back the send.
    conn = _FakeConn()
    bridge = LandingTargetBridge(
        MavlinkSettings(enable_landing_target=True, fov_x_rad=2.0, fov_y_rad=2.0),
        connection=conn,
        clock=FakeClock(times=[2.0]),
        heartbeat=_fresh_monitor(),
    )
    det, result = _result_with((140, 90, 160, 110))
    assert bridge.publish(det, result) is True
    assert len(conn.mav.calls) == 1
    args, kwargs = conn.mav.calls[0]
    assert kwargs == {}
    assert args[0] == 2_000_000  # time_usec from clock
    assert args[1] == 0  # target_num
    assert args[2] == 12  # MAV_FRAME_BODY_FRD
    assert args[3] == pytest.approx(0.5)  # angle_x


def test_publish_body_frd_sends_eight_positional_args_no_position_valid() -> None:
    # Characterization (pre-NED refactor): body_frd path sends exactly 8 positional args,
    # frame=MAV_FRAME_BODY_FRD(12), and NO x/y/z/position_valid (defaults => position_valid=0).
    conn = _FakeConn()
    bridge = LandingTargetBridge(
        MavlinkSettings(enable_landing_target=True, fov_x_rad=2.0, fov_y_rad=2.0),
        connection=conn,
        clock=FakeClock(times=[2.0]),
        heartbeat=_fresh_monitor(),
    )
    det, result = _result_with((140, 90, 160, 110))
    assert bridge.publish(det, result) is True
    args, kwargs = conn.mav.calls[0]
    assert len(args) == 8
    assert kwargs == {}
    assert args[2] == 12  # MAV_FRAME_BODY_FRD


def test_publish_body_frd_unchanged_after_frame_dispatch() -> None:
    # Task 12 guard: with frame="body_frd" (default) explicitly set, the frame-dispatch
    # refactor must still emit exactly the pre-refactor 8-positional-arg wire format.
    conn = _FakeConn()
    bridge = LandingTargetBridge(
        MavlinkSettings(enable_landing_target=True, frame="body_frd", fov_x_rad=2.0, fov_y_rad=2.0),
        connection=conn,
        clock=FakeClock(times=[2.0]),
        heartbeat=_fresh_monitor(),
    )
    det, result = _result_with((140, 90, 160, 110))
    assert bridge.publish(det, result) is True
    args, kwargs = conn.mav.calls[0]
    assert len(args) == 8 and args[2] == 12  # still MAV_FRAME_BODY_FRD, 8 positional
    assert kwargs == {}


def test_compute_time_usec_publish_default_uses_clock() -> None:
    conn = _FakeConn()
    bridge = LandingTargetBridge(
        MavlinkSettings(enable_landing_target=True, capture_time_source="publish"),
        connection=conn,
        clock=FakeClock(times=[7.0]),
        heartbeat=_fresh_monitor(),
    )
    assert bridge._compute_time_usec(capture_t=5.0) == 7_000_000  # ignores capture_t


def test_compute_time_usec_capture_uses_frame_time_plus_offset() -> None:
    conn = _FakeConn()
    bridge = LandingTargetBridge(
        MavlinkSettings(
            enable_landing_target=True, capture_time_source="capture", timesync_enabled=True
        ),
        connection=conn,
        clock=FakeClock(times=[7.0]),
        heartbeat=_fresh_monitor(),
        timesync=TimeSync(offset_us=500_000),
    )
    assert bridge._compute_time_usec(capture_t=5.0) == 5_500_000


def test_compute_time_usec_capture_timesync_disabled_ignores_offset() -> None:
    # timesync_enabled is load-bearing: with a TimeSync wired but the flag OFF, the capture
    # path must use the RAW capture timestamp (no offset) — proving the flag actually gates it.
    conn = _FakeConn()
    bridge = LandingTargetBridge(
        MavlinkSettings(
            enable_landing_target=True, capture_time_source="capture", timesync_enabled=False
        ),
        connection=conn,
        clock=FakeClock(times=[7.0]),
        heartbeat=_fresh_monitor(),
        timesync=TimeSync(offset_us=500_000),
    )
    assert bridge._compute_time_usec(capture_t=5.0) == 5_000_000  # offset NOT applied


def test_compute_time_usec_capture_without_timesync_uses_raw_capture_t() -> None:
    # capture_time_source="capture" but no TimeSync injected -> use capture_t directly
    # (no offset available), still ignoring the publish-time clock.
    conn = _FakeConn()
    bridge = LandingTargetBridge(
        MavlinkSettings(enable_landing_target=True, capture_time_source="capture"),
        connection=conn,
        clock=FakeClock(times=[7.0]),
        heartbeat=_fresh_monitor(),
    )
    assert bridge._compute_time_usec(capture_t=5.0) == 5_000_000


def test_compute_time_usec_capture_falls_back_to_clock_when_capture_t_none() -> None:
    # capture_time_source="capture" but capture_t is None (no frame timestamp available)
    # -> fall back to the publish-time wall clock rather than crashing.
    conn = _FakeConn()
    bridge = LandingTargetBridge(
        MavlinkSettings(enable_landing_target=True, capture_time_source="capture"),
        connection=conn,
        clock=FakeClock(times=[9.0]),
        heartbeat=_fresh_monitor(),
        timesync=TimeSync(offset_us=500_000),
    )
    assert bridge._compute_time_usec(capture_t=None) == 9_000_000


class _FixedPose:
    """A :class:`PoseSource` fake returning a caller-supplied pose (or ``None``) forever."""

    def __init__(self, pose: VehiclePose | None) -> None:
        self._pose = pose

    def latest(self) -> VehiclePose | None:
        return self._pose


def test_local_ned_sends_position_valid_with_pose() -> None:
    conn = _FakeConn()
    bridge = LandingTargetBridge(
        MavlinkSettings(
            enable_landing_target=True, frame="local_ned", fov_x_rad=1.2, fov_y_rad=0.7
        ),
        connection=conn,
        clock=FakeClock(times=[3.0]),
        heartbeat=_fresh_monitor(),
        pose_source=_FixedPose(VehiclePose(alt_agl_m=100.0, heading_deg=0.0, pitch_deg=90.0)),
    )
    det, result = _result_with((95, 95, 105, 105))  # true centre (100,100) of the 200x200 result
    assert bridge.publish(det, result) is True
    assert len(conn.mav.calls) == 1
    args, kwargs = conn.mav.calls[0]
    assert kwargs == {}  # local_ned path sends all 14 args positionally (verified against impl)
    assert args[2] == 1  # MAV_FRAME_LOCAL_NED
    # nadir centre => target directly below: north=0, east=0, down=alt_agl_m.
    # Pin the full x/y/z payload (not just frame + position_valid) so an arg-order regression
    # (e.g. a y<->z swap) fails here instead of silently reaching the autopilot.
    assert args[8] == pytest.approx(0.0, abs=1e-6)  # north/x
    assert args[9] == pytest.approx(0.0, abs=1e-6)  # east/y
    assert args[10] == pytest.approx(100.0)  # down/z == alt_agl_m
    # position_valid is always positional at index 13 for this call site (see bridge.py's
    # _send_local_ned docstring); read it there rather than via a kwargs-or-fallback guess.
    assert args[13] == 1


def test_local_ned_suppresses_when_no_pose() -> None:
    conn = _FakeConn()
    bridge = LandingTargetBridge(
        MavlinkSettings(
            enable_landing_target=True, frame="local_ned", fov_x_rad=1.2, fov_y_rad=0.7
        ),
        connection=conn,
        clock=FakeClock(times=[3.0]),
        heartbeat=_fresh_monitor(),
        pose_source=_FixedPose(None),
    )
    det, result = _result_with((315, 235, 325, 245))
    assert bridge.publish(det, result) is False
    assert conn.mav.calls == []  # fail-safe: never send position_valid=1 without a pose
    assert bridge.suppressed_snapshot() == {"no_pose": 1}  # counted distinctly by reason


def test_local_ned_suppresses_when_ray_unprojectable() -> None:
    # A pose *is* present but yields an unusable ray (alt_agl_m <= 0 is always unprojectable
    # per project_pixel_to_ned) -> must suppress just like the no-pose case, not send a bogus
    # position_valid=1.
    conn = _FakeConn()
    bridge = LandingTargetBridge(
        MavlinkSettings(
            enable_landing_target=True, frame="local_ned", fov_x_rad=1.2, fov_y_rad=0.7
        ),
        connection=conn,
        clock=FakeClock(times=[3.0]),
        heartbeat=_fresh_monitor(),
        pose_source=_FixedPose(VehiclePose(alt_agl_m=0.0, heading_deg=0.0, pitch_deg=90.0)),
    )
    det, result = _result_with((315, 235, 325, 245))
    assert bridge.publish(det, result) is False
    assert conn.mav.calls == []
    assert bridge.suppressed_snapshot() == {"unprojectable": 1}


def test_ned_suppression_accumulates_by_reason_and_logs_reason() -> None:
    # Two consecutive no-pose suppressions: the 1st logs (throttle streak == 1) and records
    # reason="no_pose"; the 2nd takes the throttle's don't-log branch. Both are counted in the
    # per-reason snapshot, disambiguating this cause from a heartbeat-gate suppression.
    conn = _FakeConn()
    bridge = LandingTargetBridge(
        MavlinkSettings(
            enable_landing_target=True, frame="local_ned", fov_x_rad=1.2, fov_y_rad=0.7
        ),
        connection=conn,
        clock=FakeClock(times=[3.0, 4.0]),
        heartbeat=_fresh_monitor(),
        pose_source=_FixedPose(None),
    )
    det, result = _result_with((95, 95, 105, 105))
    with capture_logs() as logs:
        assert bridge.publish(det, result) is False  # 1st: logs
        assert bridge.publish(det, result) is False  # 2nd: throttle don't-log branch
    assert bridge.suppressed_snapshot() == {"no_pose": 2}
    ned_warnings = [e for e in logs if e.get("reason") == "no_pose"]
    assert len(ned_warnings) == 1  # exactly the 1st logged, carrying the disambiguating reason
    assert conn.mav.calls == []


def test_suppressed_snapshot_disambiguates_heartbeat_from_pose() -> None:
    # One bridge, two distinct suppression causes: a stale heartbeat (gate) then a fresh
    # heartbeat with no pose (local_ned). The snapshot must key them separately, not conflate
    # them into one opaque total the way the pre-hardening single counter did.
    clk = SettableClock(100.0)
    mon = HeartbeatMonitor(clk, max_age_s=2.0)  # no beat yet -> stale
    conn = _FakeConn()
    bridge = LandingTargetBridge(
        MavlinkSettings(
            enable_landing_target=True, frame="local_ned", fov_x_rad=1.2, fov_y_rad=0.7
        ),
        connection=conn,
        clock=FakeClock(times=[3.0, 4.0]),
        heartbeat=mon,
        pose_source=_FixedPose(None),
    )
    det, result = _result_with((95, 95, 105, 105))
    assert bridge.publish(det, result) is False  # stale heartbeat -> no_heartbeat
    mon.beat(100.0)  # now fresh -> gate opens, reaches local_ned with no pose
    assert bridge.publish(det, result) is False  # no pose -> no_pose
    assert bridge.suppressed_snapshot() == {"no_heartbeat": 1, "no_pose": 1}


def test_publish_opens_connection_via_factory_when_none() -> None:
    conn = _FakeConn()
    bridge = LandingTargetBridge(
        MavlinkSettings(enable_landing_target=True),
        connection_factory=lambda: conn,
        heartbeat=_fresh_monitor(),
    )
    det, result = _result_with((90, 90, 110, 110))
    assert bridge.publish(det, result) is True
    assert len(conn.mav.calls) == 1


def test_publish_suppressed_when_no_heartbeat() -> None:
    # Default MavlinkSettings has require_heartbeat=True; with no beat the gate fails closed.
    conn = _FakeConn()
    bridge = LandingTargetBridge(MavlinkSettings(enable_landing_target=True), connection=conn)
    det, result = _result_with((90, 90, 110, 110))
    assert bridge.publish(det, result) is False
    assert conn.mav.calls == []


def test_publish_suppressed_when_heartbeat_stale() -> None:
    conn = _FakeConn()
    clk = SettableClock(100.0)
    mon = HeartbeatMonitor(clk, max_age_s=2.0)
    mon.beat(t=100.0)
    clk.t = 105.0  # aged past the window -> stale
    bridge = LandingTargetBridge(
        MavlinkSettings(enable_landing_target=True), connection=conn, heartbeat=mon
    )
    det, result = _result_with((90, 90, 110, 110))
    assert bridge.publish(det, result) is False
    assert conn.mav.calls == []


def test_publish_without_gate_when_require_heartbeat_false() -> None:
    conn = _FakeConn()
    bridge = LandingTargetBridge(
        MavlinkSettings(enable_landing_target=True, require_heartbeat=False),
        connection=conn,
    )
    det, result = _result_with((90, 90, 110, 110))
    assert bridge.publish(det, result) is True
    assert len(conn.mav.calls) == 1


def test_poll_heartbeat_records_target_beat_and_opens_gate() -> None:
    conn = _FakeConn(heartbeats=[_FakeMsg(src_system=1, src_component=1)])
    bridge = LandingTargetBridge(
        MavlinkSettings(enable_landing_target=True, target_system=1, target_component=1),
        connection=conn,
    )
    det, result = _result_with((90, 90, 110, 110))
    assert bridge.publish(det, result) is False  # gate closed before any beat
    assert bridge.poll_heartbeat() is True  # consumed the HEARTBEAT
    assert bridge.publish(det, result) is True  # gate now open
    assert len(conn.mav.calls) == 1


def test_poll_heartbeat_ignores_non_target_source() -> None:
    conn = _FakeConn(heartbeats=[_FakeMsg(src_system=99, src_component=1)])
    bridge = LandingTargetBridge(
        MavlinkSettings(enable_landing_target=True, target_system=1, target_component=1),
        connection=conn,
    )
    assert bridge.poll_heartbeat() is False  # wrong system id -> ignored
    det, result = _result_with((90, 90, 110, 110))
    assert bridge.publish(det, result) is False  # gate stays closed


def test_poll_heartbeat_wildcard_accepts_any_source() -> None:
    conn = _FakeConn(heartbeats=[_FakeMsg(src_system=42, src_component=7)])
    bridge = LandingTargetBridge(
        MavlinkSettings(enable_landing_target=True, target_system=0, target_component=0),
        connection=conn,
    )
    assert bridge.poll_heartbeat() is True


def test_poll_heartbeat_noop_without_connection_or_gate() -> None:
    # Factory yields nothing -> the link can't open -> nothing to read (no real IO).
    bridge = LandingTargetBridge(
        MavlinkSettings(enable_landing_target=True), connection_factory=lambda: None
    )
    assert bridge.poll_heartbeat() is False
    # Gate disabled -> poll is a no-op even with a connection (never touches the link).
    conn = _FakeConn(heartbeats=[_FakeMsg()])
    bridge2 = LandingTargetBridge(
        MavlinkSettings(enable_landing_target=True, require_heartbeat=False),
        connection=conn,
    )
    assert bridge2.poll_heartbeat() is False
    assert conn.recv_calls == 0


def test_poll_heartbeat_lazily_opens_link_via_factory() -> None:
    # Gate on, connection never explicitly started: poll must open the link (via the factory)
    # so heartbeats can be received and the gate can eventually open — not stay closed forever.
    conn = _FakeConn(heartbeats=[_FakeMsg(src_system=1, src_component=1)])
    bridge = LandingTargetBridge(
        MavlinkSettings(enable_landing_target=True, target_system=1, target_component=1),
        connection_factory=lambda: conn,
    )
    assert bridge.poll_heartbeat() is True  # lazily opened the link and consumed the beat
    det, result = _result_with((90, 90, 110, 110))
    assert bridge.publish(det, result) is True  # gate now open
    assert len(conn.mav.calls) == 1


def test_poll_heartbeat_swallows_link_open_error() -> None:
    def _boom_factory() -> object:
        raise OSError("cannot open link")

    bridge = LandingTargetBridge(
        MavlinkSettings(enable_landing_target=True), connection_factory=_boom_factory
    )
    assert bridge.poll_heartbeat() is False  # open error swallowed, loop survives


def test_poll_heartbeat_swallows_read_error() -> None:
    class _BoomConn:
        def __init__(self) -> None:
            self.mav = _FakeMav()

        def recv_match(self, *, type: str, blocking: bool) -> object:  # noqa: A002
            raise OSError("link read failed")

    bridge = LandingTargetBridge(
        MavlinkSettings(enable_landing_target=True), connection=_BoomConn()
    )
    assert bridge.poll_heartbeat() is False  # error is swallowed, not raised


def test_close_is_idempotent_and_closes_connection() -> None:
    conn = _FakeConn()
    bridge = LandingTargetBridge(MavlinkSettings(), connection=conn)
    bridge.close()
    bridge.close()
    assert conn.closed is True


def test_close_swallows_connection_close_error() -> None:
    class _BadConn:
        def __init__(self) -> None:
            self.mav = _FakeMav()

        def close(self) -> None:
            raise OSError("link already gone")

    bridge = LandingTargetBridge(MavlinkSettings(), connection=_BadConn())
    bridge.close()  # best-effort teardown must not raise


def test_close_with_non_callable_close_attr() -> None:
    class _NoCloseConn:
        mav = _FakeMav()
        close = None  # not callable

    bridge = LandingTargetBridge(MavlinkSettings(), connection=_NoCloseConn())
    bridge.close()  # no-op, must not raise


def test_publish_raises_mavlink_error_when_no_connection() -> None:
    # Gate open (fresh beat) but the factory yields no connection: publish must fail loud,
    # not silently drop — a missing link is a real fault, distinct from a heartbeat miss.
    bridge = LandingTargetBridge(
        MavlinkSettings(enable_landing_target=True),
        connection_factory=lambda: None,
        heartbeat=_fresh_monitor(),
    )
    det, result = _result_with((90, 90, 110, 110))
    with pytest.raises(MavlinkError):
        bridge.publish(det, result)


def test_suppressed_publish_logs_are_rate_limited() -> None:
    # The gate stays closed; with log_every=3 the warning fires on the 1st and 3rd suppression
    # only (rate-limited), never sends, and carries the structured reason codes.
    conn = _FakeConn()
    bridge = LandingTargetBridge(
        MavlinkSettings(enable_landing_target=True), connection=conn, log_every=3
    )
    det, result = _result_with((90, 90, 110, 110))
    with capture_logs() as logs:
        for _ in range(4):
            assert bridge.publish(det, result) is False
    assert conn.mav.calls == []
    warnings = [e for e in logs if e["event"].startswith("LANDING_TARGET suppressed")]
    assert [e["suppressed"] for e in warnings] == [1, 3]  # 1st + every 3rd
    assert warnings[0]["reasons"] == ("no_heartbeat",)


def test_log_every_must_be_positive() -> None:
    with pytest.raises(ValueError, match="log_every"):
        LandingTargetBridge(MavlinkSettings(), log_every=0)


def test_heartbeat_status_reflects_gate_state() -> None:
    # Gate disabled -> None; gate enabled -> a report whose freshness tracks beats.
    off = LandingTargetBridge(MavlinkSettings(require_heartbeat=False))
    assert off.heartbeat_status() is None

    mon = _fresh_monitor()
    on = LandingTargetBridge(MavlinkSettings(enable_landing_target=True), heartbeat=mon)
    status = on.heartbeat_status()
    assert status is not None and status.fresh is True


def test_poll_heartbeat_logs_lost_and_reacquired_transitions() -> None:
    # Edge-triggered: acquired (first fresh) -> lost (aged out) -> reacquired, each logged once.
    clk = SettableClock(100.0)
    mon = HeartbeatMonitor(clk, max_age_s=2.0)
    conn = _FakeConn(
        heartbeats=[_FakeMsg(1, 1), _FakeMsg(1, 1), None, _FakeMsg(1, 1)]  # beat, beat, none, beat
    )
    bridge = LandingTargetBridge(
        MavlinkSettings(enable_landing_target=True, target_system=1, target_component=1),
        connection=conn,
        heartbeat=mon,
    )
    with capture_logs() as logs:
        bridge.poll_heartbeat()  # beat at t=100 -> acquired
        bridge.poll_heartbeat()  # still fresh -> no transition, no duplicate log
        clk.t = 105.0  # age out
        bridge.poll_heartbeat()  # recv None -> stale -> lost
        bridge.poll_heartbeat()  # beat at t=105 -> reacquired
    events = [e["event"] for e in logs]
    # Match the bridge's full gate-open text, not a bare "acquired" substring: HeartbeatMonitor
    # also emits a debug-level "autopilot heartbeat acquired" on the first beat, which
    # capture_logs() sees or drops depending on the ambient structlog level (INFO filtering is
    # order-dependent across the suite). Matching the specific transition message asserts the
    # edge-triggered acquisition fired exactly once, independent of that log-level state.
    assert sum("acquired; LANDING_TARGET gate open" in e for e in events) == 1  # exactly once
    assert any("lost" in e for e in events)
    assert any("reacquired" in e for e in events)


def test_poll_heartbeat_swallows_target_check_error() -> None:
    # A malformed message whose accessors raise must not kill the caller's loop (the target
    # check + beat() run inside the guard).
    class _BadMsg:
        def get_srcSystem(self) -> int:  # noqa: N802 - pymavlink accessor name
            raise ValueError("garbled")

        def get_srcComponent(self) -> int:  # noqa: N802 - pymavlink accessor name
            return 1

    conn = _FakeConn(heartbeats=[_BadMsg()])
    bridge = LandingTargetBridge(MavlinkSettings(enable_landing_target=True), connection=conn)
    assert bridge.poll_heartbeat() is False  # error swallowed
