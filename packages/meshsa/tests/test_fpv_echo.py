"""Echo-suppression regression (Phase 0 Errata E1.2).

A scripted transport echoes every write; ``poll_inbound`` must return zero echoes
while the counter increments, and real telemetry interleaved with echoes must
pass through.
"""

from __future__ import annotations

from _fpv_helpers import FakeCrsfSerial, link_statistics_bytes

from meshsa.fpv.config import CrsfLinkSettings
from meshsa.fpv.crsf.frame import CrsfFrame, CrsfFrameType
from meshsa.fpv.crsf.link import CrsfLink


def _open(**settings_kwargs) -> tuple[CrsfLink, FakeCrsfSerial]:
    fake = FakeCrsfSerial(echo=settings_kwargs.pop("echo", True))
    link = CrsfLink(CrsfLinkSettings(**settings_kwargs), serial=fake)
    link.open()
    return link, fake


def test_transmitted_rc_echo_is_suppressed():
    link, _fake = _open()
    link.send_rc([1500] * 4)  # echoed back onto the line by the fake
    frames = link.poll_inbound()
    assert frames == []
    assert link.echoes_suppressed == 1


def test_telemetry_passes_through_interleaved_with_echoes():
    link, fake = _open()
    link.send_rc([1500] * 4)  # echo queued
    fake.feed(link_statistics_bytes(addr=0xEA))  # a genuine module reply
    link.send_rc([1600] * 4)  # another echo queued
    frames = link.poll_inbound()
    assert [f.type for f in frames] == [CrsfFrameType.LINK_STATISTICS]
    assert link.echoes_suppressed == 2
    assert link.frames_received == 1


def test_rule_a_suppresses_self_addressed_rc_not_in_dedupe():
    # No auto-echo; feed a fresh RC frame addressed as ourselves that was never
    # transmitted (so the dedupe deque is empty -> only rule A can fire).
    link, fake = _open(echo=False, crsf_address=0xC8)
    rc = CrsfFrame(addr=0xC8, type=CrsfFrameType.RC_CHANNELS_PACKED, payload=bytes(22))
    fake.feed(rc.to_bytes())
    assert link.poll_inbound() == []
    assert link.echoes_suppressed == 1


def test_rule_a_does_not_blanket_drop_foreign_rc():
    # An RC frame addressed to someone else is NOT our echo -> passes through.
    link, fake = _open(echo=False, crsf_address=0xC8)
    rc = CrsfFrame(addr=0xEA, type=CrsfFrameType.RC_CHANNELS_PACKED, payload=bytes(22))
    fake.feed(rc.to_bytes())
    frames = link.poll_inbound()
    assert [f.addr for f in frames] == [0xEA]
    assert link.echoes_suppressed == 0


def test_rule_b_exact_match_independent_of_address():
    # Transmit with self-addr 0xC8 (recorded in dedupe), then change our address
    # so rule A would no longer match — rule B (exact bytes) must still suppress.
    settings = CrsfLinkSettings(crsf_address=0xC8, echo_dedupe_len=4)
    fake = FakeCrsfSerial(echo=True)
    link = CrsfLink(settings, serial=fake)
    link.open()
    link.send_rc([1500] * 4)
    settings.crsf_address = 0xEA  # rule A now targets a different address
    assert link.poll_inbound() == []  # suppressed by rule B
    assert link.echoes_suppressed == 1
