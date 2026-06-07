import json
import struct
import xml.etree.ElementTree as ET

import pytest

from meshsa import (
    ArmSpec,
    AxisChannel,
    ButtonChannel,
    ButtonGroupChannel,
    JoystickChannelSource,
    JoystickState,
    JsEvent,
    MspPilot,
    RcMapping,
    RoundRobinTelemetry,
    axis_to_us,
    default_mapping,
    load_mapping,
    make_cot_publisher,
    parse_js_event,
)
from meshsa.rc import (
    RC_MAX,
    RC_MID,
    RC_MIN,
    _channel_from_dict,
)


# ------------------------------------------------------------------ event parsing
def _ev(value: int, etype: int, number: int) -> bytes:
    return struct.pack("<IhBB", 0, value, etype, number)


def test_parse_axis_button_other_and_init_flag():
    assert parse_js_event(_ev(123, 0x02, 4)) == JsEvent("axis", 4, 123)
    assert parse_js_event(_ev(1, 0x01, 7)) == JsEvent("button", 7, 1)
    # init flag (0x80) is masked off — still an axis
    assert parse_js_event(_ev(5, 0x82, 0)) == JsEvent("axis", 0, 5)
    assert parse_js_event(_ev(0, 0x00, 0)).kind == "other"


def test_parse_wrong_size_raises():
    with pytest.raises(ValueError):
        parse_js_event(b"\x00\x00\x00")


def test_joystick_state_tracks_latest():
    st = JoystickState()
    st.apply(JsEvent("axis", 1, 100))
    st.apply(JsEvent("axis", 1, 200))  # latest wins
    st.apply(JsEvent("button", 3, 1))
    st.apply(JsEvent("other", 0, 9))  # ignored
    assert st.axis(1) == 200
    assert st.button(3) == 1
    assert st.axis(99, default=-1) == -1
    assert st.button(99, default=7) == 7


# --------------------------------------------------------------------- axis mapping
def test_axis_to_us_center_endpoints_clamp_reverse():
    assert axis_to_us(0) == RC_MID
    assert axis_to_us(32767) == RC_MAX
    assert axis_to_us(-32767) == RC_MIN
    assert axis_to_us(99999) == RC_MAX  # clamp high
    assert axis_to_us(-99999) == RC_MIN  # clamp low
    assert axis_to_us(32767, reverse=True) == RC_MIN
    assert axis_to_us(0, reverse=True) == RC_MID


def test_axis_to_us_custom_range_and_zero_span():
    # a 0..32767 throttle axis maps bottom->1000, top->2000
    assert axis_to_us(0, in_min=0, in_max=32767) == RC_MIN
    assert axis_to_us(32767, in_min=0, in_max=32767) == RC_MAX
    assert axis_to_us(123, in_min=5, in_max=5) == RC_MID  # degenerate span


def test_channel_specs_resolve():
    st = JoystickState()
    st.apply(JsEvent("axis", 0, 32767))
    assert AxisChannel(0).resolve(st) == RC_MAX
    assert AxisChannel(0, reverse=True).resolve(st) == RC_MIN

    assert ButtonChannel(2).resolve(st) == RC_MIN  # not pressed -> off
    st.apply(JsEvent("button", 2, 1))
    assert ButtonChannel(2).resolve(st) == RC_MAX  # pressed -> on

    grp = ButtonGroupChannel(positions=((5, RC_MIN), (6, RC_MAX)))
    assert grp.resolve(st) == RC_MID  # none active -> default mid
    st.apply(JsEvent("button", 6, 1))
    assert grp.resolve(st) == RC_MAX  # 3-pos high
    st.apply(JsEvent("button", 5, 1))
    assert grp.resolve(st) == RC_MIN  # first active wins


# ------------------------------------------------------------------- mapping config
def test_rcmapping_from_dict_all_channel_types():
    m = RcMapping.from_dict(
        {
            "channels": [
                {"type": "axis", "index": 0, "reverse": True, "in_min": 0, "in_max": 100},
                {"type": "button", "index": 1, "on_us": 1900, "off_us": 1100},
                {"type": "buttons", "positions": [[2, 1000], [3, 2000]], "default_us": 1500},
            ],
            "arm": {"channel": 2, "source_button": 1},
            "throttle_channel": 0,
            "failsafe_timeout_s": 0.25,
        }
    )
    assert isinstance(m.channels[0], AxisChannel) and m.channels[0].reverse
    assert isinstance(m.channels[1], ButtonChannel) and m.channels[1].on_us == 1900
    assert isinstance(m.channels[2], ButtonGroupChannel)
    assert m.arm == ArmSpec(channel=2, source_button=1)
    assert m.throttle_channel == 0 and m.failsafe_timeout_s == 0.25


def test_channel_from_dict_unknown_type_raises():
    with pytest.raises(ValueError):
        _channel_from_dict({"type": "nope"})


def test_default_mapping_is_eight_channels():
    m = default_mapping()
    assert len(m.channels) == 8
    assert m.arm.channel == 4 and m.throttle_channel == 3


# ----------------------------------------------------------- joystick channel source
class FakeReader:
    """Yields a scripted list of events per read(); empty list once exhausted."""

    def __init__(self, scripted: list[list[JsEvent]]) -> None:
        self._scripted = list(scripted)

    def read(self) -> list[JsEvent]:
        return self._scripted.pop(0) if self._scripted else []


def _arm_mapping() -> RcMapping:
    return RcMapping(
        channels=(
            AxisChannel(0),  # roll
            AxisChannel(1),  # pitch
            AxisChannel(3),  # yaw
            AxisChannel(2),  # throttle
            ButtonChannel(0),  # AUX1 = arm (overwritten by ArmSpec)
            ButtonGroupChannel(positions=((1, RC_MIN), (2, RC_MAX))),
        ),
        arm=ArmSpec(channel=4, source_button=0),
        throttle_channel=3,
        failsafe_timeout_s=0.5,
    )


def test_no_auto_arm_until_switch_released_then_engaged():
    # Arm switch is ON from the very first event -> must NOT arm (never seen released).
    reader = FakeReader(
        [
            [JsEvent("button", 0, 1)],  # arm switch already on at startup
            [JsEvent("button", 0, 0)],  # released -> now ready
            [JsEvent("button", 0, 1)],  # engaged intentionally -> arm
        ]
    )
    src = JoystickChannelSource(reader, _arm_mapping())
    assert src.channels(now=1.0)[4] == RC_MIN  # not armed (auto-arm prevented)
    assert src.channels(now=1.1)[4] == RC_MIN  # released, still not armed
    assert src.channels(now=1.2)[4] == RC_MAX  # armed


def test_stale_input_forces_disarm_and_throttle_min():
    reader = FakeReader(
        [
            [JsEvent("button", 0, 0), JsEvent("axis", 2, 32767)],  # fresh: throttle high, ready
            [JsEvent("button", 0, 1)],  # arm engaged, still fresh
        ]
    )
    m = _arm_mapping()
    src = JoystickChannelSource(reader, m)
    src.channels(now=10.0)  # establishes last_event + arm_ready
    armed = src.channels(now=10.1)
    assert armed[4] == RC_MAX and armed[3] == RC_MAX  # armed, throttle passes through

    # No new events and time advances past the failsafe window -> fail safe.
    safe = src.channels(now=11.0)
    assert safe[4] == RC_MIN  # disarmed
    assert safe[3] == RC_MIN  # throttle forced to min


def test_no_rearm_after_failsafe_until_switch_recycled():
    # The safety invariant: after a stale/failsafe event, resuming fresh input with the arm
    # switch STILL held on must NOT re-arm — the switch must be physically re-cycled.
    reader = FakeReader(
        [
            [JsEvent("button", 0, 0), JsEvent("axis", 2, 32767)],  # ready, throttle high
            [JsEvent("button", 0, 1)],  # arm engaged
            [],  # (time jumps past failsafe below) -> stale
            [JsEvent("axis", 0, 1)],  # fresh input resumes, arm switch still latched ON
            [JsEvent("button", 0, 0)],  # release
            [JsEvent("button", 0, 1)],  # intentional re-engage
        ]
    )
    src = JoystickChannelSource(reader, _arm_mapping())
    src.channels(now=10.0)
    assert src.channels(now=10.1)[4] == RC_MAX  # armed
    safe = src.channels(now=11.0)  # no events + time jump -> stale
    assert safe[4] == RC_MIN and safe[3] == RC_MIN  # failsafe: disarm + throttle min
    resumed = src.channels(now=11.1)  # fresh input, switch still ON
    assert resumed[4] == RC_MIN  # MUST stay disarmed (no silent re-arm)
    src.channels(now=11.2)  # release
    assert src.channels(now=11.3)[4] == RC_MAX  # re-armed only after re-cycle


def test_armspec_requires_exactly_one_source():
    with pytest.raises(ValueError):
        ArmSpec(channel=0)  # neither button nor axis
    with pytest.raises(ValueError):
        ArmSpec(channel=0, source_button=1, source_axis=2)  # both


def test_armspec_axis_source_active_above_threshold():
    a = ArmSpec(channel=0, source_axis=7, axis_threshold=0)
    st = JoystickState()
    st.apply(JsEvent("axis", 7, -32767))
    assert not a.is_active(st)  # switch low
    st.apply(JsEvent("axis", 7, 32767))
    assert a.is_active(st)  # switch high → arm requested


def test_arm_via_axis_switch_end_to_end():
    # Mirror the real radio: ARM driven by a switch exposed as an axis.
    mapping = RcMapping(
        channels=(AxisChannel(0), AxisChannel(1), AxisChannel(2), AxisChannel(3), AxisChannel(7)),
        arm=ArmSpec(channel=4, source_axis=7, axis_threshold=0),
        throttle_channel=3,
    )
    reader = FakeReader(
        [
            [JsEvent("axis", 7, -32767)],  # arm switch low → ready
            [JsEvent("axis", 7, 32767)],  # arm switch high → armed
        ]
    )
    src = JoystickChannelSource(reader, mapping)
    assert src.channels(now=1.0)[4] == RC_MIN  # disarmed
    assert src.channels(now=1.1)[4] == RC_MAX  # armed


def test_rcmapping_rejects_out_of_range_indices():
    chans = (AxisChannel(0), AxisChannel(1))
    with pytest.raises(ValueError):
        RcMapping(channels=chans, arm=ArmSpec(channel=5, source_button=0))
    with pytest.raises(ValueError):
        RcMapping(channels=chans, arm=ArmSpec(channel=0, source_button=0), throttle_channel=9)


def test_msppilot_rejects_nonpositive_hz():
    with pytest.raises(ValueError):
        MspPilot(FakeSource([]), FakeSink(), hz=0)


def test_axes_map_into_channels():
    reader = FakeReader([[JsEvent("axis", 0, 32767), JsEvent("axis", 1, -32767)]])
    src = JoystickChannelSource(reader, _arm_mapping())
    chans = src.channels(now=1.0)
    assert chans[0] == RC_MAX and chans[1] == RC_MIN


def test_disarm_channels_are_safe():
    src = JoystickChannelSource(FakeReader([]), _arm_mapping())
    d = src.disarm_channels()
    assert d[4] == RC_MIN  # arm low
    assert d[3] == RC_MIN  # throttle min


# --------------------------------------------------------------------- the loop
class FakeSink:
    def __init__(self) -> None:
        self.sent: list[list[int]] = []

    def send(self, channels) -> None:
        self.sent.append(list(channels))


class FakeSource:
    def __init__(self, seq) -> None:
        self._seq = list(seq)

    def channels(self, now: float):
        return self._seq.pop(0) if self._seq else [RC_MID] * 4


def _clock(values):
    it = iter(values)
    return lambda: next(it)


def test_tick_sends_channels_and_skips_none():
    sink = FakeSink()
    src = FakeSource([[1500, 1500, 1000, 1500], None])
    pilot = MspPilot(src, sink, clock=_clock([0.0, 0.0]), sleep=lambda _d: None)
    pilot.tick()
    pilot.tick()  # None -> no send
    assert sink.sent == [[1500, 1500, 1000, 1500]]


def test_tick_telemetry_is_decimated():
    calls: list[int] = []
    pilot = MspPilot(
        FakeSource([[1] * 4] * 5),
        FakeSink(),
        telemetry_interval_s=1.0,
        on_telemetry=lambda: calls.append(1),
        clock=_clock([0.0, 0.5, 1.0, 1.2]),
        sleep=lambda _d: None,
    )
    for _ in range(4):
        pilot.tick()
    assert len(calls) == 2  # fires at t=0.0 and t=1.0 only


def test_tick_telemetry_hook_exception_swallowed():
    def boom() -> None:
        raise RuntimeError("telemetry blew up")

    pilot = MspPilot(
        FakeSource([[1] * 4]),
        FakeSink(),
        telemetry_interval_s=0.0,
        on_telemetry=boom,
        clock=_clock([0.0]),
        sleep=lambda _d: None,
    )
    pilot.tick()  # must not raise


def test_run_streams_then_disarms_on_exit():
    sink = FakeSink()
    src = FakeSource([[1500] * 4, [1500] * 4])
    state = {"n": 0}
    holder: dict[str, MspPilot] = {}

    def sleeper(_d: float) -> None:
        state["n"] += 1
        if state["n"] >= 2:
            holder["p"]._running = False

    pilot = MspPilot(
        src, sink, disarm=[1000, 1000, 1000, 1000], clock=_clock([0.0, 0.0]), sleep=sleeper
    )
    holder["p"] = pilot
    pilot.run()
    assert sink.sent[-1] == [1000, 1000, 1000, 1000]  # final disarm frame
    assert len(sink.sent) == 3  # 2 RC ticks + disarm


def test_send_disarm_noop_when_unset():
    sink = FakeSink()
    MspPilot(FakeSource([]), sink)._send_disarm()
    assert sink.sent == []


def test_send_disarm_swallows_sink_error():
    class BadSink:
        def send(self, channels) -> None:
            raise OSError("serial gone")

    pilot = MspPilot(FakeSource([]), BadSink(), disarm=[1000])
    pilot._send_disarm()  # must not raise


def test_stop_before_start_is_safe():
    MspPilot(FakeSource([]), FakeSink()).stop()  # thread is None branch


# ----------------------------------------------------- round-robin telemetry + cot publisher
def test_round_robin_reads_one_per_call_and_accumulates():
    reads: list[str] = []

    def r_gps(_b):
        reads.append("gps")
        return {"lat": 10000000, "lon": 20000000, "alt": 5}

    def r_an(_b):
        reads.append("an")
        return {"vbat": 11.8, "rssi": 1023}

    def r_at(_b):
        reads.append("at")
        return {"roll": 2}

    rr = RoundRobinTelemetry(
        object(), source_uid="fc-1", callsign="FC1", readers=[r_gps, r_an, r_at], clock=lambda: 1.0
    )
    f1 = rr()  # reads ONLY gps
    assert reads == ["gps"]
    assert json.loads(f1)["lat"] == pytest.approx(1.0) and json.loads(f1)["msg_id"] == "fc-1:1"
    f2 = rr()  # reads ONLY analog; sample now carries battery/rssi
    assert reads == ["gps", "an"] and "VBAT 11.8V" in json.loads(f2)["remarks"]
    rr()  # attitude
    f4 = rr()  # round-robin wraps back to gps
    assert reads == ["gps", "an", "at", "gps"]
    assert json.loads(f4)["msg_id"] == "fc-1:4"  # seq advances once per emitted frame


def test_round_robin_uses_fallback_and_swallows_reader_error():
    def boom(_b):
        raise RuntimeError("serial hiccup")

    rr = RoundRobinTelemetry(
        object(), readers=[boom], fallback_lat=1.0, fallback_lon=2.0, clock=lambda: 0.0
    )
    assert json.loads(rr())["lat"] == pytest.approx(1.0)  # error swallowed, fallback used


def test_round_robin_none_without_position():
    rr = RoundRobinTelemetry(object(), readers=[lambda _b: {"vbat": 1.0}], clock=lambda: 0.0)
    assert rr() is None  # telemetry but no fix and no fallback -> no frame


def test_make_cot_publisher_encodes_and_skips_none():
    frame = json.dumps(
        {"src": "uav-1", "callsign": "U", "msg_id": "uav-1:1", "ts": 1.0, "lat": 1.0, "lon": 2.0}
    ).encode()
    sent: list[bytes] = []
    frames = iter([frame, None])
    publish = make_cot_publisher(lambda: next(frames), sent.append)
    publish()  # frame -> CoT bytes sent
    assert len(sent) == 1 and b"<event" in sent[0] and b'uid="uav-1"' in sent[0]
    publish()  # None -> skipped
    assert len(sent) == 1


def test_msppilot_rejects_negative_hz():
    with pytest.raises(ValueError):
        MspPilot(FakeSource([]), FakeSink(), hz=-1.0)


def test_rcmapping_rejects_negative_index():
    with pytest.raises(ValueError):
        RcMapping(
            channels=(AxisChannel(0), AxisChannel(1)), arm=ArmSpec(channel=-1, source_button=0)
        )


# ------------------------------------------------------- e2e: full pilot arm/failsafe lifecycle
def test_pilot_lifecycle_through_loop_to_sink():
    """Regression: drive the REAL JoystickChannelSource through MspPilot.tick into a sink and
    assert the whole arm/failsafe lifecycle reaches the wire — not just channels() in isolation."""
    reader = FakeReader(
        [
            [JsEvent("button", 0, 0), JsEvent("axis", 2, 32767)],  # t0: ready, throttle high
            [JsEvent("button", 0, 1)],  # t1: arm engaged → armed
            [],  # t2: stale (time jump) → failsafe
            [JsEvent("axis", 0, 1)],  # t3: fresh input, arm still latched ON
            [JsEvent("button", 0, 0)],  # t4: release
            [JsEvent("button", 0, 1)],  # t5: intentional re-engage → armed
        ]
    )
    sink = FakeSink()
    pilot = MspPilot(
        JoystickChannelSource(reader, _arm_mapping()),
        sink,
        hz=50.0,
        clock=_clock([10.0, 10.1, 11.0, 11.1, 11.2, 11.3]),
        sleep=lambda _d: None,
    )
    for _ in range(6):
        pilot.tick()
    arm = [frame[4] for frame in sink.sent]  # ch4 = ARM
    thr = [frame[3] for frame in sink.sent]  # ch3 = throttle (throttle_channel)
    assert arm == [RC_MIN, RC_MAX, RC_MIN, RC_MIN, RC_MIN, RC_MAX]  # no auto-arm, re-cycle req'd
    assert thr[2] == RC_MIN  # failsafe forced throttle to min on the stale tick


# ------------------------------------------- e2e: round-robin telemetry → real codecs → CoT XML
def test_round_robin_telemetry_to_cot_xml():
    sent: list[bytes] = []
    rr = RoundRobinTelemetry(
        object(),
        source_uid="fc-1",
        callsign="FC1",
        readers=[
            lambda _b: {"lat": 10000000, "lon": 20000000, "alt": 5},
            lambda _b: {"vbat": 11.8, "rssi": 1023},
        ],
        clock=lambda: 1700000000.0,
    )
    publish = make_cot_publisher(rr, sent.append, pli_type="a-f-A-M-F-Q")
    publish()  # gps read → position known → CoT emitted
    publish()  # analog read → remarks now carry battery/rssi
    assert len(sent) == 2
    ev0 = ET.fromstring(sent[0])
    assert ev0.attrib["type"].startswith("a-f-A")  # honors the air pli_type
    assert float(ev0.find("point").attrib["lat"]) == pytest.approx(1.0)
    remarks = ET.fromstring(sent[1]).find("detail/remarks")
    assert remarks is not None and "VBAT 11.8V" in remarks.text and "RSSI 1023" in remarks.text


def test_round_robin_publisher_skips_when_no_position():
    sent: list[bytes] = []
    rr = RoundRobinTelemetry(object(), readers=[lambda _b: {"vbat": 1.0}], clock=lambda: 0.0)
    make_cot_publisher(rr, sent.append)()  # telemetry-only, no fix, no fallback → nothing sent
    assert sent == []


def test_load_mapping_from_file(tmp_path):
    p = tmp_path / "m.json"
    p.write_text(
        json.dumps(
            {
                "channels": [{"type": "axis", "index": 0}],
                "arm": {"channel": 0, "source_button": 0},
                "throttle_channel": 0,
            }
        )
    )
    m = load_mapping(str(p))
    assert len(m.channels) == 1 and m.arm.channel == 0


def test_start_then_stop_runs_thread():
    sink = FakeSink()
    pilot = MspPilot(FakeSource([]), sink, hz=200.0, disarm=[1000] * 4)
    pilot.start()
    pilot.stop()  # joins the worker thread
    assert pilot._thread is None
