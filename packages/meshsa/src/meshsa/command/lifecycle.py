"""The command lifecycle: send → match COMMAND_ACK → bounded retry → fail-closed.

This is the stateful piece the §10 amendment moves out of any "pure codec": it
owns retries, ACK correlation, and audit writes, driving an injected
:class:`CommandLink` (the live pymavlink link in production, a fake in tests).

ACK semantics (designed against the MAVLink command spec; the research's exact
resend/match claims were *refuted*, so the conservative rules are explicit here):

* ``MAV_RESULT_ACCEPTED`` → success, return immediately.
* ``DENIED`` / ``UNSUPPORTED`` / ``FAILED`` / ``CANCELLED`` → **terminal failure**,
  fail-closed, no further retries (the autopilot gave a definite no).
* ``TEMPORARILY_REJECTED`` / ``IN_PROGRESS`` / no ACK within the timeout → retry,
  up to ``max_attempts``; after the bound, fail-closed and recorded as failed.

An ACK is matched only when its ``command`` equals the sent command **and** (when
``expect_system`` is set) its ``source_system`` matches — non-matching ACKs on the
shared link are skipped, not mistaken for ours.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

import structlog

from ..protocols import Clock
from .commands import CommanderSettings, CommandSpec

_log = structlog.get_logger("meshsa.command.lifecycle")

# MAV_RESULT enum (common dialect), inlined to keep the package dependency-free.
MAV_RESULT_ACCEPTED = 0
MAV_RESULT_TEMPORARILY_REJECTED = 1
MAV_RESULT_DENIED = 2
MAV_RESULT_UNSUPPORTED = 3
MAV_RESULT_FAILED = 4
MAV_RESULT_IN_PROGRESS = 5
MAV_RESULT_CANCELLED = 6

#: Results that end the command with no retry (a definite refusal from the vehicle).
_TERMINAL_FAILURES: frozenset[int] = frozenset(
    {MAV_RESULT_DENIED, MAV_RESULT_UNSUPPORTED, MAV_RESULT_FAILED, MAV_RESULT_CANCELLED}
)


@dataclass(frozen=True)
class Ack:
    """A received COMMAND_ACK, reduced to what the matcher needs."""

    command: int
    result: int
    source_system: int = 1


@runtime_checkable
class CommandLink(Protocol):
    """The medium toward the autopilot. The live impl owns the pymavlink link."""

    # send: pack (via the live MAVLink instance) and transmit ``spec``.
    def send(self, spec: CommandSpec) -> None: ...

    # recv_ack: return the next COMMAND_ACK, or None if none arrives within timeout.
    def recv_ack(self, timeout: float) -> Ack | None: ...


@runtime_checkable
class AuditLog(Protocol):
    """Append-only audit. ``record`` must never silently drop (block-then-raise)."""

    def record(self, event: str, data: dict[str, Any]) -> None: ...


@dataclass(frozen=True)
class CommandOutcome:
    """The terminal result of one supervised command execution."""

    spec: CommandSpec
    accepted: bool
    result: int | None
    attempts: int
    reason: str


class CommandSender:
    """Runs the ACK/retry/timeout state machine for confirmed commands.

    Synchronous and blocking by design (it waits for ACKs); the audit contract
    requires it to run **off** the asyncio loop thread (in an executor).
    """

    def __init__(
        self,
        link: CommandLink,
        audit: AuditLog,
        *,
        settings: CommanderSettings,
        clock: Clock,
        expect_system: int | None = None,
    ) -> None:
        self._link = link
        self._audit = audit
        self._s = settings
        self._clock = clock
        self._expect_system = expect_system

    def execute(self, spec: CommandSpec) -> CommandOutcome:
        """Send ``spec`` with bounded retries; return its :class:`CommandOutcome`.

        Every attempt, accept, reject, retry, and final failure is audited. Audit
        writes are intentionally **not** swallowed: if the audit raises (overflow),
        the command fails closed and the error propagates.
        """
        base = {"command": spec.command, "name": spec.name}
        # Discard ACKs left over from a prior command before we send this one, so a
        # stale ACK can't be mistaken for this command's reply. Optional on the link
        # (only the live pump buffers ACKs); fakes/simple links omit it.
        drain = getattr(self._link, "drain", None)
        if callable(drain):
            drain()
        last_result: int | None = None
        for attempt in range(1, self._s.max_attempts + 1):
            self._audit.record("command_attempt", {**base, "attempt": attempt})
            self._link.send(spec)
            ack = self._await_ack(spec.command)

            if ack is None:
                _log.info("no ack; will retry if attempts remain", **base, attempt=attempt)
                self._audit.record("command_no_ack", {**base, "attempt": attempt})
                continue

            last_result = ack.result
            if ack.result == MAV_RESULT_ACCEPTED:
                self._audit.record("command_accepted", {**base, "attempt": attempt})
                return CommandOutcome(spec, True, ack.result, attempt, "")
            if ack.result in _TERMINAL_FAILURES:
                self._audit.record(
                    "command_rejected", {**base, "attempt": attempt, "result": ack.result}
                )
                return CommandOutcome(spec, False, ack.result, attempt, "terminal_reject")
            # TEMPORARILY_REJECTED / IN_PROGRESS -> retry
            self._audit.record("command_retry", {**base, "attempt": attempt, "result": ack.result})

        self._audit.record(
            "command_failed", {**base, "attempts": self._s.max_attempts, "result": last_result}
        )
        return CommandOutcome(spec, False, last_result, self._s.max_attempts, "exhausted_retries")

    def _await_ack(self, command: int) -> Ack | None:
        """Wait up to ``ack_timeout_s`` for a matching ACK, skipping unrelated ones."""
        deadline = self._clock.now() + self._s.ack_timeout_s
        while True:
            remaining = deadline - self._clock.now()
            if remaining <= 0:
                return None
            ack = self._link.recv_ack(remaining)
            if ack is None:
                return None
            if ack.command != command:
                continue
            if self._expect_system is not None and ack.source_system != self._expect_system:
                continue
            return ack


def is_accepted(results: Iterable[int]) -> bool:
    """True iff every result in ``results`` is ``MAV_RESULT_ACCEPTED`` (helper for callers)."""
    materialised = list(results)
    return bool(materialised) and all(r == MAV_RESULT_ACCEPTED for r in materialised)
