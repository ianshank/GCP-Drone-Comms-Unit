"""Joystick → MSP RC control — pilot a Betaflight FC from the host over USB.

This is the *control* (uplink) counterpart to :mod:`meshsa.transports.msp_source`
(telemetry/downlink). A :class:`ChannelSource` produces RC channel values (µs) and an
:class:`MspPilot` loop streams them to the FC via ``MSP_SET_RAW_RC`` at a fixed rate. The
joystick is one ``ChannelSource``; a sim/autonomy controller is another — same loop, same
FC sink — so this seam outlives the bench-pilot use case (HITL / computer-in-the-loop).

Design (mirrors the rest of the package):
  * All hardware lives behind injectable, ``# pragma: no cover`` seams — the
    ``/dev/input/js0`` reader (:class:`FileJoystickReader`) and the yamspy RC sink
    (:class:`MspRcSink`). Everything else — event parsing, stick→channel mapping, the
    arm/failsafe state machine, the rate-limited loop — is pure and unit-tested with fakes.
  * The loop is a **sync thread** (blocking serial I/O, like ``msp_source._reader``) with an
    injectable ``clock``/``sleep`` so tests are deterministic without real time.

⚠️ SAFETY: this drives real motors. The loop starts **disarmed / throttle-min**, **never
auto-arms** (the arm switch must be seen released once before it is honoured, so a switch
left ON at startup does nothing), **fails safe** (disarm + throttle-min) when joystick input
goes stale, and sends a final **disarm** frame on stop. Bench-test **with props off**.
"""

from __future__ import annotations

import json
import struct
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

import structlog

from .cot import CotCodec
from .telemetry import TelemetryCodec
from .transports.msp_source import DEFAULT_MSP_READERS, build_telemetry_frame

_log = structlog.get_logger("meshsa.rc")

# Linux joystick event: struct js_event { __u32 time; __s16 value; __u8 type; __u8 number; }
_JS_EVENT_FMT = "<IhBB"
JS_EVENT_SIZE = struct.calcsize(_JS_EVENT_FMT)  # 8 bytes
_JS_TYPE_BUTTON = 0x01
_JS_TYPE_AXIS = 0x02
_JS_TYPE_INIT = 0x80  # ORed into type on the synthetic events sent at open

#: RC pulse bounds (microseconds), the MSP_SET_RAW_RC convention.
RC_MIN = 1000
RC_MID = 1500
RC_MAX = 2000
_AXIS_MAX = 32767


# --------------------------------------------------------------------------- events
@dataclass(frozen=True)
class JsEvent:
    """A decoded Linux joystick event. ``kind`` is ``"axis"``, ``"button"`` or ``"other"``."""

    kind: str
    number: int
    value: int


def parse_js_event(buf: bytes) -> JsEvent:
    """Decode one 8-byte ``js_event``. The init flag (0x80) is masked off."""
    if len(buf) != JS_EVENT_SIZE:
        raise ValueError(f"joystick event must be {JS_EVENT_SIZE} bytes, got {len(buf)}")
    _ts, value, etype, number = struct.unpack(_JS_EVENT_FMT, buf)
    base = etype & ~_JS_TYPE_INIT
    if base == _JS_TYPE_AXIS:
        kind = "axis"
    elif base == _JS_TYPE_BUTTON:
        kind = "button"
    else:
        kind = "other"
    return JsEvent(kind=kind, number=number, value=value)


class JoystickState:
    """Latest value per axis/button, updated by applying :class:`JsEvent` s."""

    def __init__(self) -> None:
        self.axes: dict[int, int] = {}
        self.buttons: dict[int, int] = {}

    def apply(self, ev: JsEvent) -> None:
        if ev.kind == "axis":
            self.axes[ev.number] = ev.value
        elif ev.kind == "button":
            self.buttons[ev.number] = ev.value

    def axis(self, n: int, default: int = 0) -> int:
        return self.axes.get(n, default)

    def button(self, n: int, default: int = 0) -> int:
        return self.buttons.get(n, default)


# --------------------------------------------------------------------------- mapping
def axis_to_us(
    raw: int, *, in_min: int = -_AXIS_MAX, in_max: int = _AXIS_MAX, reverse: bool = False
) -> int:
    """Map a raw axis value in ``[in_min, in_max]`` to ``[RC_MIN, RC_MAX]`` µs, clamped.

    Symmetric defaults put a centered stick (0) at ``RC_MID``; a throttle axis that rests at
    one end simply lands at ``RC_MIN``/``RC_MAX``. ``reverse`` flips the channel.
    """
    span = in_max - in_min
    if span == 0:
        return RC_MID
    frac = (raw - in_min) / span
    if reverse:
        frac = 1.0 - frac
    us = round(RC_MIN + frac * (RC_MAX - RC_MIN))
    return max(RC_MIN, min(RC_MAX, us))


@dataclass(frozen=True)
class AxisChannel:
    """RC channel driven by a joystick axis."""

    index: int
    reverse: bool = False
    in_min: int = -_AXIS_MAX
    in_max: int = _AXIS_MAX

    def resolve(self, state: JoystickState) -> int:
        return axis_to_us(
            state.axis(self.index), in_min=self.in_min, in_max=self.in_max, reverse=self.reverse
        )


@dataclass(frozen=True)
class ButtonChannel:
    """RC channel driven by a single (2-position) button: pressed → ``on_us`` else ``off_us``."""

    index: int
    on_us: int = RC_MAX
    off_us: int = RC_MIN

    def resolve(self, state: JoystickState) -> int:
        return self.on_us if state.button(self.index) else self.off_us


@dataclass(frozen=True)
class ButtonGroupChannel:
    """RC channel for an N-position switch exposed as buttons.

    ``positions`` is an ordered list of ``(button_index, us)``; the first active button
    wins, otherwise ``default_us``. A 3-position switch is two buttons + a mid default,
    e.g. ``positions=[(5, RC_MIN), (6, RC_MAX)], default_us=RC_MID``.
    """

    positions: tuple[tuple[int, int], ...]
    default_us: int = RC_MID

    def resolve(self, state: JoystickState) -> int:
        for idx, us in self.positions:
            if state.button(idx):
                return us
        return self.default_us


ChannelSpec = AxisChannel | ButtonChannel | ButtonGroupChannel


@dataclass(frozen=True)
class ArmSpec:
    """Where ARM lives and what drives it. ``channel`` is the RC index ARM outputs on.

    Exactly one source must be set: ``source_button`` (a switch exposed as a joystick button)
    OR ``source_axis`` (a switch exposed as an axis — common on EdgeTX radios — considered
    active when its value is ``>= axis_threshold``).
    """

    channel: int
    source_button: int | None = None
    source_axis: int | None = None
    axis_threshold: int = 0
    armed_us: int = RC_MAX
    disarmed_us: int = RC_MIN

    def __post_init__(self) -> None:
        if (self.source_button is None) == (self.source_axis is None):
            raise ValueError("ArmSpec needs exactly one of source_button or source_axis")

    def is_active(self, state: JoystickState) -> bool:
        if self.source_axis is not None:
            return state.axis(self.source_axis) >= self.axis_threshold
        assert self.source_button is not None  # guaranteed by __post_init__
        return bool(state.button(self.source_button))


@dataclass
class RcMapping:
    """Full stick/switch → RC channel mapping for one airframe."""

    channels: tuple[ChannelSpec, ...]
    arm: ArmSpec
    throttle_channel: int = 3  # MSP order [roll, pitch, yaw, throttle, aux…]
    failsafe_timeout_s: float = 0.5

    def __post_init__(self) -> None:
        n = len(self.channels)
        if not 0 <= self.arm.channel < n:
            raise ValueError(f"arm.channel {self.arm.channel} out of range for {n} channels")
        if not 0 <= self.throttle_channel < n:
            raise ValueError(
                f"throttle_channel {self.throttle_channel} out of range for {n} channels"
            )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RcMapping:
        return cls(
            channels=tuple(_channel_from_dict(c) for c in data["channels"]),
            arm=ArmSpec(**data["arm"]),
            throttle_channel=int(data.get("throttle_channel", 3)),
            failsafe_timeout_s=float(data.get("failsafe_timeout_s", 0.5)),
        )


def _channel_from_dict(c: dict[str, Any]) -> ChannelSpec:
    kind = c.get("type")
    if kind == "axis":
        return AxisChannel(
            index=int(c["index"]),
            reverse=bool(c.get("reverse", False)),
            in_min=int(c.get("in_min", -_AXIS_MAX)),
            in_max=int(c.get("in_max", _AXIS_MAX)),
        )
    if kind == "button":
        return ButtonChannel(
            index=int(c["index"]),
            on_us=int(c.get("on_us", RC_MAX)),
            off_us=int(c.get("off_us", RC_MIN)),
        )
    if kind == "buttons":
        return ButtonGroupChannel(
            positions=tuple((int(i), int(u)) for i, u in c["positions"]),
            default_us=int(c.get("default_us", RC_MID)),
        )
    raise ValueError(f"unknown channel type: {kind!r}")


def default_mapping() -> RcMapping:
    """A starting-point mapping for a RadioMaster Pocket in EdgeTX USB-joystick mode.

    Axis/button numbers are hardware-specific — calibrate with the daemon's ``--dry-run``.
    8 channels: roll/pitch/yaw/throttle + ARM (AUX1) + a 3-pos mode switch (AUX2) + two spare.
    """
    return RcMapping(
        channels=(
            AxisChannel(index=0),  # ch1 roll
            AxisChannel(index=1),  # ch2 pitch
            AxisChannel(index=3),  # ch3 yaw
            AxisChannel(index=2),  # ch4 throttle
            ButtonChannel(index=0),  # ch5 AUX1 = ARM (overwritten by ArmSpec each tick)
            ButtonGroupChannel(positions=((1, RC_MIN), (2, RC_MAX))),  # ch6 AUX2 = 3-pos mode
            AxisChannel(index=4),  # ch7 spare
            AxisChannel(index=5),  # ch8 spare
        ),
        arm=ArmSpec(channel=4, source_button=0),
        throttle_channel=3,
    )


def load_mapping(path: str) -> RcMapping:
    """Load an :class:`RcMapping` from a JSON file (the daemon's ``--mapping``)."""
    with open(path, encoding="utf-8") as fh:
        return RcMapping.from_dict(json.load(fh))


# ----------------------------------------------------------------------- protocols
@runtime_checkable
class ChannelSource(Protocol):
    """Produces RC channels for a given time. ``None`` ⇒ no fresh command (loop fails safe)."""

    def channels(self, now: float) -> list[int] | None: ...


@runtime_checkable
class RcSink(Protocol):
    def send(self, channels: Sequence[int]) -> None: ...


@runtime_checkable
class JoystickReader(Protocol):
    def read(self) -> list[JsEvent]: ...


# ------------------------------------------------------------------ channel sources
class JoystickChannelSource:
    """A :class:`ChannelSource` driven by a joystick, with the arm/failsafe state machine.

    Each call drains the reader, updates state, resolves channels from the mapping, then
    enforces safety: ARM is honoured only after the switch has been seen released once and
    while input is fresh; stale input forces disarm + throttle-min.
    """

    def __init__(self, reader: JoystickReader, mapping: RcMapping) -> None:
        self._reader = reader
        self._mapping = mapping
        self._state = JoystickState()
        self._last_event_t: float | None = None
        self._arm_ready = False

    def channels(self, now: float) -> list[int]:
        events = self._reader.read()
        for ev in events:
            self._state.apply(ev)
        if events:
            self._last_event_t = now

        chans = [spec.resolve(self._state) for spec in self._mapping.channels]
        stale = (
            self._last_event_t is None
            or (now - self._last_event_t) > self._mapping.failsafe_timeout_s
        )

        arm = self._mapping.arm
        arm_active = arm.is_active(self._state)
        if not arm_active:
            self._arm_ready = True  # switch observed released → future ON is intentional
        if stale:
            # After ANY failsafe, require the arm switch to be physically re-cycled before
            # motors can spin again — never silently re-arm when fresh input resumes with the
            # switch still held ON (e.g. a USB glitch that tripped the timeout).
            self._arm_ready = False
        armed = self._arm_ready and arm_active and not stale

        chans[arm.channel] = arm.armed_us if armed else arm.disarmed_us
        if stale:
            chans[self._mapping.throttle_channel] = RC_MIN
        return chans

    def disarm_channels(self) -> list[int]:
        """The safe frame: every channel resolved with no input, ARM low, throttle min."""
        empty = JoystickState()
        chans = [spec.resolve(empty) for spec in self._mapping.channels]
        chans[self._mapping.arm.channel] = self._mapping.arm.disarmed_us
        chans[self._mapping.throttle_channel] = RC_MIN
        return chans


# ---------------------------------------------------------------- default hardware seams
class FileJoystickReader:  # pragma: no cover - needs /dev/input/js0
    """Non-blocking reader over a Linux ``/dev/input/jsN`` device."""

    def __init__(self, path: str = "/dev/input/js0") -> None:
        import fcntl
        import os

        self._f = open(path, "rb")  # noqa: SIM115 - long-lived device handle, closed in close()
        flags = fcntl.fcntl(self._f, fcntl.F_GETFL)
        fcntl.fcntl(self._f, fcntl.F_SETFL, flags | os.O_NONBLOCK)

    def read(self) -> list[JsEvent]:
        events: list[JsEvent] = []
        while True:
            try:
                buf = self._f.read(JS_EVENT_SIZE)
            except BlockingIOError:
                break
            if not buf or len(buf) < JS_EVENT_SIZE:
                break
            events.append(parse_js_event(buf))
        return events

    def close(self) -> None:
        self._f.close()


class MspRcSink:  # pragma: no cover - needs yamspy + FC
    """Sends RC over MSP via ``fast_msp_rc_cmd`` (it drains the FC ack, keeping the serial
    framing clean for interleaved telemetry reads on the same handle)."""

    def __init__(self, board: Any) -> None:
        self._board = board

    def send(self, channels: Sequence[int]) -> None:
        self._board.fast_msp_rc_cmd(list(channels))


# ----------------------------------------------------------------------- the loop
class MspPilot:
    """Fixed-rate loop: stream a :class:`ChannelSource` to an :class:`RcSink`, and call an
    optional ``on_telemetry`` hook every ``telemetry_interval_s`` (decimated so telemetry
    reads barely perturb RC timing). Runs on its own sync thread."""

    def __init__(
        self,
        source: ChannelSource,
        sink: RcSink,
        *,
        hz: float = 50.0,
        telemetry_interval_s: float = 1.0,
        on_telemetry: Callable[[], None] | None = None,
        disarm: Sequence[int] | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if hz <= 0:
            raise ValueError("hz must be > 0")
        self._source = source
        self._sink = sink
        self._interval = 1.0 / hz
        self._tele_interval = telemetry_interval_s
        self._on_telemetry = on_telemetry
        self._disarm = list(disarm) if disarm is not None else None
        self._clock = clock
        self._sleep = sleep
        self._running = False
        self._last_tele: float | None = None
        self._thread: threading.Thread | None = None

    def tick(self) -> None:
        now = self._clock()
        chans = self._source.channels(now)
        if chans is not None:
            self._sink.send(chans)
        if self._on_telemetry is not None and (
            self._last_tele is None or (now - self._last_tele) >= self._tele_interval
        ):
            self._last_tele = now
            try:
                self._on_telemetry()
            except Exception:
                _log.warning("rc on_telemetry hook failed")

    def run(self) -> None:
        """Loop until :meth:`stop`; always emits a final disarm frame on exit."""
        self._running = True
        try:
            while self._running:
                self.tick()
                self._sleep(self._interval)
        finally:
            self._send_disarm()

    def _send_disarm(self) -> None:
        if self._disarm is None:
            return
        try:
            self._sink.send(self._disarm)
        except Exception:
            _log.warning("rc disarm-on-stop send failed")

    def start(self) -> None:
        self._thread = threading.Thread(target=self._guarded_run, name="msp-pilot", daemon=True)
        self._thread.start()

    def _guarded_run(self) -> None:  # pragma: no cover - thread entrypoint, logic in run()
        try:
            self.run()
        except Exception:
            _log.exception("msp pilot loop crashed")
            self._send_disarm()

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None


# ------------------------------------------------------------- combined telemetry (uplink-side)
class RoundRobinTelemetry:
    """A telemetry frame source that reads **one** MSP message per call (round-robin).

    On the pilot's single serial-owning thread, polling all three MSP messages at once would
    block the RC loop for the duration of three round-trips; reading one per call bounds the
    per-call serial time to a single read while a rolling sample accumulates across calls.
    Returns a ``telemetry`` codec frame (bytes) each call, or ``None`` until a position (a GPS
    fix or a configured fallback) is known. ``readers`` and ``clock`` are injectable for tests;
    the defaults talk to a real yamspy board.
    """

    def __init__(
        self,
        board: Any,
        *,
        source_uid: str = "fc-1",
        callsign: str = "FC1",
        readers: Sequence[Callable[[Any], dict[str, Any]]] | None = None,
        fallback_lat: float | None = None,
        fallback_lon: float | None = None,
        fallback_hae: float = 0.0,
        coord_scale: float = 1e7,
        alt_scale: float = 1.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._board = board
        self._readers = tuple(readers) if readers is not None else DEFAULT_MSP_READERS
        self._i = 0
        self._sample: dict[str, Any] = {}
        self._seq = 0
        self._uid = source_uid
        self._callsign = callsign
        self._fallback = (fallback_lat, fallback_lon, fallback_hae)
        self._coord_scale = coord_scale
        self._alt_scale = alt_scale
        self._clock = clock

    def __call__(self) -> bytes | None:
        reader = self._readers[self._i]
        self._i = (self._i + 1) % len(self._readers)
        try:
            self._sample.update(reader(self._board) or {})
        except Exception:
            _log.debug("msp telemetry read failed")
        frame = build_telemetry_frame(
            self._sample or None,
            seq=self._seq + 1,
            source_uid=self._uid,
            callsign=self._callsign,
            now=self._clock(),
            coord_scale=self._coord_scale,
            alt_scale=self._alt_scale,
            fallback_lat=self._fallback[0],
            fallback_lon=self._fallback[1],
            fallback_hae=self._fallback[2],
        )
        if frame is not None:
            self._seq += 1
        return frame


def make_cot_publisher(
    frame_source: Callable[[], bytes | None],
    send_cot: Callable[[bytes], None],
    *,
    pli_type: str = "a-f-A-M-F-Q",
) -> Callable[[], None]:
    """Build an ``on_telemetry`` hook: pull a telemetry frame, encode it to CoT, and hand the
    bytes to ``send_cot``. ``send_cot`` is injected (the daemon bridges it to a TAK transport on
    the asyncio loop), keeping this — and the None-frame skip — testable without sockets."""
    tele, cot = TelemetryCodec(), CotCodec(pli_type=pli_type)

    def publish() -> None:
        frame = frame_source()
        if frame is None:
            return
        send_cot(cot.encode(tele.decode(frame)))

    return publish
