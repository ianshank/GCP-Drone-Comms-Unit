"""CommandService orchestration: stage -> confirm -> interlock -> execute (fakes-only)."""

import pytest
from conftest import SeqIdFactory

from meshsa.command import (
    Ack,
    ArmBlockedError,
    CommanderSettings,
    CommandNotAllowedError,
    CommandSender,
    CommandService,
    ConfirmationGate,
    ForceConfirmationRequired,
    UnknownConfirmationError,
)
from meshsa.command.lifecycle import MAV_RESULT_ACCEPTED
from meshsa.fpv.link_health import HealthReport, HealthState


class FixedClock:
    def __init__(self, t: float = 1_000.0) -> None:
        self._t = t

    def now(self) -> float:
        return self._t


class FakeLink:
    def __init__(self, acks):
        self.sent = []
        self._acks = list(acks)

    def send(self, spec):
        self.sent.append(spec)

    def recv_ack(self, timeout):
        return self._acks.pop(0) if self._acks else None


class FakeAudit:
    def __init__(self):
        self.events = []

    def record(self, event, data):
        self.events.append((event, data))

    def names(self):
        return [e for e, _ in self.events]


def _service(*, allowed, force=False, acks=None, health=None, clock=None):
    settings = CommanderSettings(allowed=frozenset(allowed), allow_force_disarm=force)
    clk = clock or FixedClock()
    link = FakeLink(acks if acks is not None else [Ack(0, MAV_RESULT_ACCEPTED)])
    audit = FakeAudit()
    sender = CommandSender(link, audit, settings=settings, clock=clk)
    svc = CommandService(
        gate=ConfirmationGate(SeqIdFactory()),
        sender=sender,
        settings=settings,
        audit=audit,
        clock=clk,
        health_provider=health,
    )
    return svc, audit, link


def _ok_report(t_mono: float) -> HealthReport:
    return HealthReport(state=HealthState.OK, arm_permitted=True, reasons=(), t_mono=t_mono)


def test_stage_returns_token_and_audits():
    svc, audit, _ = _service(allowed=["rtl"])
    staged = svc.stage("rtl")
    assert staged.confirmation_id == "id-1"
    assert staged.name == "rtl"
    assert staged.requires_force_confirm is False
    assert "command_staged" in audit.names()


def test_stage_rejects_disallowed_command():
    svc, _, _ = _service(allowed=["rtl"])
    with pytest.raises(CommandNotAllowedError):
        svc.stage("arm")


def test_confirm_executes_and_audits():
    # RTL command id is 20; the ack must match it for the sender to accept.
    svc, audit, link = _service(allowed=["rtl"], acks=[Ack(20, MAV_RESULT_ACCEPTED)])
    token = svc.stage("rtl").confirmation_id
    outcome = svc.confirm(token)
    assert outcome.accepted is True
    assert len(link.sent) == 1
    assert "command_confirmed" in audit.names()


def test_confirm_unknown_token_raises():
    svc, _, _ = _service(allowed=["rtl"])
    with pytest.raises(UnknownConfirmationError):
        svc.confirm("nope")


def test_force_disarm_needs_force_ack():
    svc, _, _ = _service(allowed=["force_disarm"], force=True)
    token = svc.stage("force_disarm").confirmation_id
    with pytest.raises(ForceConfirmationRequired):
        svc.confirm(token)  # normal confirm cannot release the force path


def test_arm_blocked_without_fresh_health():
    svc, audit, link = _service(allowed=["arm"], acks=[Ack(400, MAV_RESULT_ACCEPTED)])
    token = svc.stage("arm").confirmation_id
    with pytest.raises(ArmBlockedError):
        svc.confirm(token)
    assert "arm_blocked" in audit.names()
    assert link.sent == []  # never reached the link


def test_arm_allowed_with_fresh_ok_health():
    clk = FixedClock(1_000.5)
    svc, audit, link = _service(
        allowed=["arm"],
        acks=[Ack(400, MAV_RESULT_ACCEPTED)],
        health=lambda: _ok_report(1_000.0),
        clock=clk,
    )
    token = svc.stage("arm").confirmation_id
    outcome = svc.confirm(token)
    assert outcome.accepted is True
    assert len(link.sent) == 1


def test_cancel_discards_and_audits():
    svc, audit, _ = _service(allowed=["rtl"])
    token = svc.stage("rtl").confirmation_id
    svc.cancel(token)
    assert "command_cancelled" in audit.names()
    with pytest.raises(UnknownConfirmationError):
        svc.confirm(token)
