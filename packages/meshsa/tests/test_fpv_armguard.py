"""ArmGuard: health-gated arming, latch semantics, never-disarm (§5.6)."""

from __future__ import annotations

import pytest
from _fpv_helpers import ManualClock

from meshsa.fpv.arm_guard import ArmGuard
from meshsa.fpv.config import ArmGuardSettings
from meshsa.fpv.errors import ArmGuardError
from meshsa.fpv.link_health import HealthReport, HealthState
from meshsa.fpv.protocols import RCLink

# Channel layout: arm is index 4 (default). 1000us = disarmed, 2000us = armed.
_DISARM = [1500, 1500, 1500, 1500, 1000, 1500]
_ARM = [1500, 1500, 1500, 1500, 2000, 1500]


class FakeRCLink:
    def __init__(self) -> None:
        self.sent: list[list[int]] = []

    def send_rc(self, channels) -> None:
        self.sent.append(list(channels))


def _ok_report(clock: ManualClock) -> HealthReport:
    return HealthReport(HealthState.OK, True, (), clock.now())


def _bad_report(clock: ManualClock, state=HealthState.WARN) -> HealthReport:
    return HealthReport(state, False, ("lq_below_warn",), clock.now())


def _guard(clock=None, events=None):
    link = FakeRCLink()
    clock = clock or ManualClock()
    sink = (lambda name, data: events.append((name, data))) if events is not None else None
    guard = ArmGuard(link, ArmGuardSettings(), clock, on_event=sink)
    return guard, link, clock


def test_satisfies_rclink_protocol():
    guard, _link, _clock = _guard()
    assert isinstance(guard, RCLink)


def test_blocks_arm_without_any_report():
    guard, link, _clock = _guard()
    guard.send_rc(_ARM)
    # Arm channel clamped low; the rest of the frame is untouched.
    assert link.sent[-1][4] == ArmGuardSettings().arm_clamp_us
    assert guard.latched is False


def test_blocks_arm_with_stale_report():
    clock = ManualClock()
    guard, link, _ = _guard(clock)
    guard.update_health(_ok_report(clock))  # fresh OK now...
    clock.advance(5.0)  # ...but it is now stale (> 1.0s)
    guard.send_rc(_ARM)
    assert link.sent[-1][4] == ArmGuardSettings().arm_clamp_us
    assert guard.latched is False


def test_blocks_arm_when_health_not_permitted():
    clock = ManualClock()
    guard, link, _ = _guard(clock)
    guard.update_health(_bad_report(clock))  # fresh but arm_permitted False
    guard.send_rc(_ARM)
    assert link.sent[-1][4] == ArmGuardSettings().arm_clamp_us


def test_arm_passes_with_fresh_ok_report_and_latches():
    clock = ManualClock()
    guard, link, _ = _guard(clock)
    guard.update_health(_ok_report(clock))
    guard.send_rc(_ARM)
    assert link.sent[-1][4] == 2000  # not clamped
    assert guard.latched is True


def test_latch_never_clamps_in_flight_even_when_health_degrades():
    clock = ManualClock()
    guard, link, _ = _guard(clock)
    guard.update_health(_ok_report(clock))
    guard.send_rc(_ARM)  # armed + latched
    # Health goes stale/critical while flying; further armed frames pass untouched.
    clock.advance(10.0)
    guard.update_health(_bad_report(clock, HealthState.CRITICAL))
    guard.send_rc(_ARM)
    assert link.sent[-1][4] == 2000  # never clamped while latched


def test_operator_disarm_releases_latch_and_rearm_rechecks_health():
    clock = ManualClock()
    guard, link, _ = _guard(clock)
    guard.update_health(_ok_report(clock))
    guard.send_rc(_ARM)  # armed + latched
    assert guard.latched is True
    # Operator commands arm low -> disarm passes and releases the latch.
    guard.send_rc(_DISARM)
    assert guard.latched is False
    assert link.sent[-1][4] == 1000  # disarm not modified
    # Re-arm attempt while health is now stale -> blocked again.
    clock.advance(5.0)  # last OK report is stale
    guard.send_rc(_ARM)
    assert link.sent[-1][4] == ArmGuardSettings().arm_clamp_us
    assert guard.latched is False


def test_non_arm_channels_always_pass_through():
    clock = ManualClock()
    guard, link, _ = _guard(clock)
    # No report -> arm blocked, but every other channel is forwarded verbatim.
    guard.send_rc([900, 800, 1200, 1100, 2000, 1750])
    out = link.sent[-1]
    assert out[:4] == [900, 800, 1200, 1100]
    assert out[5] == 1750
    assert out[4] == ArmGuardSettings().arm_clamp_us


def test_disarmed_passthrough_without_report():
    guard, link, _clock = _guard()
    guard.send_rc(_DISARM)  # not arming, not latched -> verbatim
    assert link.sent[-1] == _DISARM


def test_channels_shorter_than_arm_index_raises():
    guard, _link, _clock = _guard()
    with pytest.raises(ArmGuardError, match="arm_channel_index"):
        guard.send_rc([1500, 1500])  # only 2 channels, arm index is 4


def test_arm_blocked_event_emitted_with_context():
    events: list = []
    clock = ManualClock()
    guard, _link, _ = _guard(clock, events=events)
    guard.update_health(_bad_report(clock))
    guard.send_rc(_ARM)
    assert len(events) == 1
    name, data = events[0]
    assert name == "arm_blocked"
    assert data["attempted_us"] == 2000
    assert data["clamped_to_us"] == ArmGuardSettings().arm_clamp_us
    assert data["health_state"] == "warn"
