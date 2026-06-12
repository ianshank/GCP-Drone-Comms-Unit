"""Half-duplex CRSF serial link + address prober (Phase 0 Errata E1.2/E1.3).

``CrsfLink`` is **poll-driven and owns no thread** (spec §3: the single asyncio
consumer drives it; only the flight logger has its own thread). The consumer
calls :meth:`CrsfLink.poll_inbound` at >= the loop rate; the :class:`CrsfSerial`
seam's ``read`` is non-blocking/timeout-bounded so the poll never stalls.

Echo suppression (E1.2) runs on every poll because TX and RX share one wire:

* **Rule B (primary, reliable):** every transmitted frame's exact bytes are kept
  in a short deque; an inbound frame whose bytes match is our echo. This is the
  dependable filter on a single-wire line — an echo is bitwise-identical to what
  we wrote.
* **Rule A (spec-mandated secondary):** drop ``RC_CHANNELS_PACKED`` frames whose
  address equals our own. :meth:`send_rc` writes frames addressed with
  ``crsf_address`` (we are the only RC source on this line), so this catches our
  echoes by address even after the dedupe deque has rolled over.

Mirrors :mod:`meshsa.transports.msp_source` for *injection* (an injectable
``CrsfSerial`` with a ``# pragma: no cover`` hardware default factory) — not for
threading.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import cast

import structlog

from ..config import CrsfLinkSettings, ProberSettings
from ..protocols import CrsfSerial
from .frame import CrsfFrame, CrsfFrameType, extract_frames
from .rc import pack_channels, us_to_ticks

_log = structlog.get_logger("meshsa.fpv.crsf.link")

SerialFactory = Callable[[], CrsfSerial]


def _default_serial_factory(settings: CrsfLinkSettings) -> SerialFactory:  # pragma: no cover
    """Build a pyserial-backed :class:`CrsfSerial` (real hardware; not unit-tested)."""

    def factory() -> CrsfSerial:
        import serial  # lazy: importing this module must not require pyserial

        port = serial.Serial(
            port=settings.crsf_device,
            baudrate=settings.crsf_baud,
            timeout=0,  # non-blocking reads
        )
        return cast(CrsfSerial, port)  # pyserial's Serial satisfies the Protocol

    return factory


class CrsfLink:
    """Poll-driven half-duplex CRSF link with self-echo suppression."""

    def __init__(
        self,
        settings: CrsfLinkSettings,
        *,
        serial: CrsfSerial | None = None,
        serial_factory: SerialFactory | None = None,
    ) -> None:
        self._s = settings
        self._serial = serial
        self._factory = serial_factory or _default_serial_factory(settings)
        self._buffer = bytearray()
        self._recent_tx: deque[bytes] = deque(maxlen=settings.echo_dedupe_len)
        # The RC mid-stick tick is settings-derived and constant; compute it once
        # rather than on every send_rc (called per RC cycle, 50-200 Hz).
        self._center_tick = us_to_ticks(
            (settings.rc_us_min + settings.rc_us_max) / 2,
            us_min=settings.rc_us_min,
            us_max=settings.rc_us_max,
            ticks_min=settings.rc_ticks_min,
            ticks_max=settings.rc_ticks_max,
        )
        #: Echoed (self-transmitted) frames suppressed since construction (E1.2).
        self.echoes_suppressed = 0
        #: CRC-failed frame candidates seen (bench item #5 surfaces this).
        self.crc_errors = 0
        #: Non-echo frames returned to consumers.
        self.frames_received = 0

    # -- lifecycle ---------------------------------------------------------- #

    def open(self) -> None:
        """Construct the serial port if one was not injected."""
        if self._serial is None:
            self._serial = self._factory()  # pragma: no cover - exercised via injection

    def close(self) -> None:
        """Release the serial port (idempotent)."""
        if self._serial is not None:
            self._serial.close()
            self._serial = None

    # -- transmit ----------------------------------------------------------- #

    def send_rc(self, channels: Sequence[int]) -> None:
        """Pack and transmit one RC frame; ``channels`` are microsecond values.

        Records the exact transmitted bytes for echo suppression (rule B) and
        addresses the frame with our own ``crsf_address`` (rule A).
        """
        ticks = [
            us_to_ticks(
                us,
                us_min=self._s.rc_us_min,
                us_max=self._s.rc_us_max,
                ticks_min=self._s.rc_ticks_min,
                ticks_max=self._s.rc_ticks_max,
            )
            for us in channels
        ]
        payload = pack_channels(ticks, count=self._s.rc_channel_count, pad=self._center_tick)
        frame = CrsfFrame(
            addr=self._s.crsf_address,
            type=CrsfFrameType.RC_CHANNELS_PACKED,
            payload=payload,
        )
        wire = frame.to_bytes()
        self._recent_tx.append(wire)
        self._require_serial().write(wire)

    # -- receive ------------------------------------------------------------ #

    def poll_inbound(self) -> list[CrsfFrame]:
        """Read available bytes and return echo-suppressed inbound frames."""
        chunk = self._require_serial().read(self._s.crsf_read_chunk)
        if chunk:
            self._buffer.extend(chunk)
        frames = extract_frames(
            self._buffer,
            max_frame_len=self._s.crsf_max_frame_len,
            on_crc_error=self._count_crc_error,
        )
        result: list[CrsfFrame] = []
        for frame in frames:
            if self._is_echo(frame):
                self.echoes_suppressed += 1
                _log.debug("suppressed self-echo", type=frame.type_name, addr=frame.addr)
                continue
            result.append(frame)
        self.frames_received += len(result)
        return result

    def _is_echo(self, frame: CrsfFrame) -> bool:
        # Rule A first (cheap): our own RC frames by address. This short-circuits
        # the common echo case — our transmitted RC frames carry crsf_address —
        # without re-serialising the frame for the Rule B comparison.
        if frame.type == CrsfFrameType.RC_CHANNELS_PACKED and frame.addr == self._s.crsf_address:
            return True
        # Rule B (primary, reliable): exact-byte match against recently
        # transmitted frames — catches echoes Rule A misses (e.g. a frame whose
        # address no longer matches ours).
        return frame.to_bytes() in self._recent_tx

    def _count_crc_error(self) -> None:
        self.crc_errors += 1

    def _require_serial(self) -> CrsfSerial:
        if self._serial is None:
            raise RuntimeError("CrsfLink is not open; call open() first")
        return self._serial


@dataclass
class ProbeResult:
    """Outcome of an address probe (E1.3)."""

    winner: int | None
    counts: dict[int, int] = field(default_factory=dict)
    confident: bool = False


class AddressProber:
    """Tallies non-echo, non-RC telemetry per source address and picks a winner.

    Confidence requires the winning address to clear ``probe_min_telemetry_frames``
    **and** exceed the runner-up by ``probe_margin`` (default 3x), guarding against
    residual echo artifacts (E1.3). The timing loop lives in the monitor tool; the
    tally + decision here is pure and fully unit-tested.
    """

    def __init__(self, settings: ProberSettings) -> None:
        self._s = settings
        self._candidates = frozenset(settings.probe_addresses)
        self.counts: dict[int, int] = {}

    def observe(self, frames: Iterable[CrsfFrame]) -> None:
        """Tally non-RC frames from candidate addresses (RC echoes excluded)."""
        for frame in frames:
            if frame.type == CrsfFrameType.RC_CHANNELS_PACKED:
                continue
            if frame.addr not in self._candidates:
                continue  # frame from an address outside the candidate set: noise
            self.counts[frame.addr] = self.counts.get(frame.addr, 0) + 1

    def drain(self, link: CrsfLink, iterations: int) -> None:
        """Poll ``link`` ``iterations`` times, observing each batch (echo-suppressed)."""
        for _ in range(iterations):
            self.observe(link.poll_inbound())

    def result(self) -> ProbeResult:
        """Decide the winning address subject to the min-frames + margin gates."""
        if not self.counts:
            return ProbeResult(winner=None)
        ranked = sorted(self.counts.items(), key=lambda kv: kv[1], reverse=True)
        winner_addr, winner_count = ranked[0]
        runner_up = ranked[1][1] if len(ranked) > 1 else 0
        confident = (
            winner_count >= self._s.probe_min_telemetry_frames
            and winner_count >= self._s.probe_margin * runner_up
        )
        return ProbeResult(
            winner=winner_addr if confident else None,
            counts=dict(self.counts),
            confident=confident,
        )
