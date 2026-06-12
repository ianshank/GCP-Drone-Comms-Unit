"""Address prober pass criteria (Phase 0 Errata E1.3)."""

from __future__ import annotations

from _fpv_helpers import FakeCrsfSerial, link_statistics_bytes

from meshsa.fpv.config import CrsfLinkSettings, ProberSettings
from meshsa.fpv.crsf.frame import CrsfFrame, CrsfFrameType
from meshsa.fpv.crsf.link import AddressProber, CrsfLink


def test_picks_correct_address_and_reports_zero_for_others():
    # Scripted line: echoes our RC writes AND replies with telemetry only for the
    # correct address (0xEA). The prober must pick 0xEA and ignore RC echoes.
    fake = FakeCrsfSerial(echo=True)
    link = CrsfLink(CrsfLinkSettings(crsf_address=0xC8), serial=fake)
    link.open()
    prober = AddressProber(ProberSettings(probe_min_telemetry_frames=3, probe_margin=3.0))
    for _ in range(5):
        link.send_rc([1500] * 4)  # echoes (suppressed, never counted)
        fake.feed(link_statistics_bytes(addr=0xEA))
    prober.drain(link, iterations=5)
    result = prober.result()
    assert result.winner == 0xEA
    assert result.confident is True
    assert result.counts == {0xEA: 5}  # RC echoes excluded entirely


def test_below_min_frames_is_not_confident():
    prober = AddressProber(ProberSettings(probe_min_telemetry_frames=10, probe_margin=3.0))
    prober.observe([CrsfFrame.from_bytes(link_statistics_bytes(addr=0xEA)) for _ in range(4)])
    result = prober.result()
    assert result.confident is False
    assert result.winner is None


def test_runner_up_within_margin_is_not_confident():
    prober = AddressProber(ProberSettings(probe_min_telemetry_frames=2, probe_margin=3.0))
    # 0xEA: 5 frames, 0xEC: 4 frames -> 5 < 3*4, ambiguous.
    prober.observe([CrsfFrame.from_bytes(link_statistics_bytes(addr=0xEA)) for _ in range(5)])
    prober.observe([CrsfFrame.from_bytes(link_statistics_bytes(addr=0xEC)) for _ in range(4)])
    result = prober.result()
    assert result.confident is False
    assert result.winner is None
    assert result.counts == {0xEA: 5, 0xEC: 4}


def test_clear_winner_over_margin_is_confident():
    prober = AddressProber(ProberSettings(probe_min_telemetry_frames=2, probe_margin=3.0))
    prober.observe([CrsfFrame.from_bytes(link_statistics_bytes(addr=0xEA)) for _ in range(9)])
    prober.observe([CrsfFrame.from_bytes(link_statistics_bytes(addr=0xEC)) for _ in range(2)])
    result = prober.result()
    assert result.winner == 0xEA  # 9 >= 3*2 and 9 >= min
    assert result.confident is True


def test_rc_frames_are_excluded_from_tally():
    prober = AddressProber(ProberSettings())
    rc = CrsfFrame(addr=0xEA, type=CrsfFrameType.RC_CHANNELS_PACKED, payload=bytes(22))
    prober.observe([rc, rc])
    assert prober.counts == {}


def test_empty_observation_has_no_winner():
    prober = AddressProber(ProberSettings())
    assert prober.result().winner is None
