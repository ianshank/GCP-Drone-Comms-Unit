"""ACK/retry/timeout state machine (fakes-only; no link, no hardware)."""

import pytest
from conftest import FakeClock

from meshsa.command import Ack, CommanderSettings, CommandSender
from meshsa.command.commands import _rtl
from meshsa.command.lifecycle import (
    MAV_RESULT_ACCEPTED,
    MAV_RESULT_DENIED,
    MAV_RESULT_TEMPORARILY_REJECTED,
    is_accepted,
)
from meshsa.fpv.errors import LoggerOverflowError

CMD = 20  # MAV_CMD_NAV_RETURN_TO_LAUNCH (the spec under test is _rtl())


class FixedClock:
    """A non-advancing clock: ``remaining`` stays positive so recv_ack drives termination."""

    def __init__(self, t: float = 1_000.0) -> None:
        self._t = t

    def now(self) -> float:
        return self._t


class FakeLink:
    """Records sends; ``recv_ack`` pops queued acks (a ``None`` entry == one timeout)."""

    def __init__(self, acks: list[Ack | None]) -> None:
        self.sent: list[object] = []
        self._acks = list(acks)

    def send(self, spec: object) -> None:
        self.sent.append(spec)

    def recv_ack(self, timeout: float) -> Ack | None:
        if not self._acks:
            return None
        return self._acks.pop(0)


class FakeAudit:
    def __init__(self, raise_on: str | None = None) -> None:
        self.events: list[tuple[str, dict]] = []
        self._raise_on = raise_on

    def record(self, event: str, data: dict) -> None:
        if self._raise_on is not None and event == self._raise_on:
            raise LoggerOverflowError("audit full")
        self.events.append((event, data))

    def names(self) -> list[str]:
        return [e for e, _ in self.events]


def _sender(link, audit, *, max_attempts=3, ack_timeout_s=2.0, clock=None, expect_system=None):
    settings = CommanderSettings(max_attempts=max_attempts, ack_timeout_s=ack_timeout_s)
    return CommandSender(
        link, audit, settings=settings, clock=clock or FixedClock(), expect_system=expect_system
    )


def test_accepted_first_attempt():
    link = FakeLink([Ack(CMD, MAV_RESULT_ACCEPTED)])
    audit = FakeAudit()
    out = _sender(link, audit).execute(_rtl())
    assert out.accepted is True
    assert out.result == MAV_RESULT_ACCEPTED
    assert out.attempts == 1
    assert out.reason == ""
    assert len(link.sent) == 1
    assert audit.names() == ["command_attempt", "command_accepted"]


def test_skips_non_matching_command_ack():
    link = FakeLink([Ack(999, MAV_RESULT_ACCEPTED), Ack(CMD, MAV_RESULT_ACCEPTED)])
    out = _sender(link, FakeAudit()).execute(_rtl())
    assert out.accepted is True
    assert len(link.sent) == 1  # one send; second ack matched without resending


def test_skips_ack_from_unexpected_source_system():
    link = FakeLink(
        [
            Ack(CMD, MAV_RESULT_ACCEPTED, source_system=9),
            Ack(CMD, MAV_RESULT_ACCEPTED, source_system=1),
        ]
    )
    out = _sender(link, FakeAudit(), expect_system=1).execute(_rtl())
    assert out.accepted is True


def test_terminal_failure_does_not_retry():
    link = FakeLink([Ack(CMD, MAV_RESULT_DENIED)])
    audit = FakeAudit()
    out = _sender(link, audit).execute(_rtl())
    assert out.accepted is False
    assert out.result == MAV_RESULT_DENIED
    assert out.attempts == 1
    assert out.reason == "terminal_reject"
    assert len(link.sent) == 1
    assert "command_rejected" in audit.names()


def test_temporarily_rejected_then_accepted():
    link = FakeLink([Ack(CMD, MAV_RESULT_TEMPORARILY_REJECTED), Ack(CMD, MAV_RESULT_ACCEPTED)])
    audit = FakeAudit()
    out = _sender(link, audit).execute(_rtl())
    assert out.accepted is True
    assert out.attempts == 2
    assert len(link.sent) == 2
    assert "command_retry" in audit.names()


def test_timeout_then_accepted():
    link = FakeLink([None, Ack(CMD, MAV_RESULT_ACCEPTED)])
    audit = FakeAudit()
    out = _sender(link, audit).execute(_rtl())
    assert out.accepted is True
    assert out.attempts == 2
    assert "command_no_ack" in audit.names()


def test_exhausted_retries_fail_closed():
    link = FakeLink([None, None])
    audit = FakeAudit()
    out = _sender(link, audit, max_attempts=2).execute(_rtl())
    assert out.accepted is False
    assert out.result is None
    assert out.attempts == 2
    assert out.reason == "exhausted_retries"
    assert "command_failed" in audit.names()


def test_deadline_elapses_while_skipping_non_matching_ack():
    # Advancing clock + a non-matching ack forces the `remaining <= 0` branch.
    link = FakeLink([Ack(999, MAV_RESULT_ACCEPTED)])
    out = _sender(link, FakeAudit(), max_attempts=1, clock=FakeClock()).execute(_rtl())
    assert out.accepted is False
    assert out.reason == "exhausted_retries"


def test_audit_overflow_propagates_and_fails_closed():
    link = FakeLink([Ack(CMD, MAV_RESULT_ACCEPTED)])
    audit = FakeAudit(raise_on="command_attempt")
    with pytest.raises(LoggerOverflowError):
        _sender(link, audit).execute(_rtl())


def test_is_accepted_helper():
    assert is_accepted([MAV_RESULT_ACCEPTED, MAV_RESULT_ACCEPTED]) is True
    assert is_accepted([]) is False
    assert is_accepted([MAV_RESULT_ACCEPTED, MAV_RESULT_DENIED]) is False
