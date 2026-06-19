"""Confirmation gate + pre-arm interlock predicate (fakes-only)."""

import pytest
from conftest import SeqIdFactory

from meshsa.command import (
    ConfirmationGate,
    ForceConfirmationRequired,
    UnknownConfirmationError,
    arm_allowed,
)
from meshsa.command.commands import _arm, _force_disarm
from meshsa.fpv.link_health import HealthReport, HealthState


def _report(*, permitted: bool, t_mono: float) -> HealthReport:
    return HealthReport(
        state=HealthState.OK if permitted else HealthState.CRITICAL,
        arm_permitted=permitted,
        reasons=(),
        t_mono=t_mono,
    )


# --- arm_allowed predicate ---------------------------------------------------
def test_arm_allowed_none_report_is_false():
    assert arm_allowed(None, now=100.0, max_age_s=2.0) is False


def test_arm_allowed_fresh_and_permitted_is_true():
    assert arm_allowed(_report(permitted=True, t_mono=100.0), now=101.0, max_age_s=2.0) is True


def test_arm_allowed_stale_is_false():
    assert arm_allowed(_report(permitted=True, t_mono=100.0), now=105.0, max_age_s=2.0) is False


def test_arm_allowed_fresh_but_not_permitted_is_false():
    assert arm_allowed(_report(permitted=False, t_mono=100.0), now=100.5, max_age_s=2.0) is False


# --- ConfirmationGate --------------------------------------------------------
def test_stage_then_confirm_returns_spec_then_token_is_consumed():
    gate = ConfirmationGate(SeqIdFactory())
    token = gate.stage(_arm())
    assert token == "id-1"
    assert gate.pending(token).name == "arm"
    assert gate.confirm(token).name == "arm"
    # consumed: a second confirm fails.
    with pytest.raises(UnknownConfirmationError):
        gate.confirm(token)


def test_confirm_unknown_token_raises():
    gate = ConfirmationGate(SeqIdFactory())
    with pytest.raises(UnknownConfirmationError):
        gate.confirm("nope")


def test_pending_unknown_token_raises():
    gate = ConfirmationGate(SeqIdFactory())
    with pytest.raises(UnknownConfirmationError):
        gate.pending("nope")


def test_force_command_needs_force_ack_and_stays_staged_until_then():
    gate = ConfirmationGate(SeqIdFactory())
    token = gate.stage(_force_disarm())
    # A normal confirmation can never satisfy the force path...
    with pytest.raises(ForceConfirmationRequired):
        gate.confirm(token)
    # ...and the command is left staged so a proper force-confirm still works.
    assert gate.pending(token).name == "force_disarm"
    spec = gate.confirm(token, force_ack=True)
    assert spec.name == "force_disarm"
    with pytest.raises(UnknownConfirmationError):
        gate.confirm(token, force_ack=True)


def test_cancel_discards_and_is_idempotent():
    gate = ConfirmationGate(SeqIdFactory())
    token = gate.stage(_arm())
    gate.cancel(token)
    gate.cancel(token)  # unknown now -> no error
    with pytest.raises(UnknownConfirmationError):
        gate.confirm(token)
