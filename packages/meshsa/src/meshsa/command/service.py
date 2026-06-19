"""The supervised orchestration: stage → confirm (+ interlock) → execute.

:class:`CommandService` ties the pure pieces together and is the single object the
HTTP endpoint drives. It is web-framework-free and fakes-testable; the aiohttp +
environment wiring lives in ``flightctl/run_commander.py``.

Flow per command (design §4):

1. :meth:`stage` builds the spec (allow-list + force-flag enforced) and parks it in
   the :class:`~meshsa.command.safety.ConfirmationGate`, returning a token.
2. :meth:`confirm` consumes the token (force commands need ``force_ack``), runs the
   **pre-arm interlock** for ``arm``, then hands the spec to the
   :class:`~meshsa.command.lifecycle.CommandSender` (ACK/retry/timeout, fail-closed).

Every step is audited. ``confirm`` blocks (it waits for ACKs and writes audit
records), so the endpoint must run it in an executor, off the asyncio loop thread.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ..fpv.link_health import HealthReport
from ..protocols import Clock
from .commands import CommanderSettings, build_command
from .errors import ArmBlockedError
from .lifecycle import AuditLog, CommandOutcome, CommandSender
from .safety import ConfirmationGate, arm_allowed

#: Returns the latest health report (or ``None`` if none yet), e.g. from a
#: link-health monitor fed by the telemetry stream.
HealthProvider = Callable[[], HealthReport | None]


@dataclass(frozen=True)
class StagedCommand:
    """What :meth:`CommandService.stage` returns for an operator to confirm."""

    confirmation_id: str
    name: str
    command: int
    requires_force_confirm: bool


class CommandService:
    """Stages, confirms, and executes supervised commands with a full audit trail."""

    def __init__(
        self,
        *,
        gate: ConfirmationGate,
        sender: CommandSender,
        settings: CommanderSettings,
        audit: AuditLog,
        clock: Clock,
        health_provider: HealthProvider | None = None,
    ) -> None:
        self._gate = gate
        self._sender = sender
        self._settings = settings
        self._audit = audit
        self._clock = clock
        self._health = health_provider

    def stage(self, name: str, params: dict[str, float] | None = None) -> StagedCommand:
        """Build + park a command for confirmation. Raises on a disallowed command."""
        spec = build_command(name, self._settings, **(params or {}))
        token = self._gate.stage(spec)
        self._audit.record(
            "command_staged", {"id": token, "name": spec.name, "command": spec.command}
        )
        return StagedCommand(token, spec.name, spec.command, spec.requires_force_confirm)

    def cancel(self, token: str) -> None:
        """Discard a staged command (idempotent)."""
        self._gate.cancel(token)
        self._audit.record("command_cancelled", {"id": token})

    def confirm(self, token: str, *, force_ack: bool = False) -> CommandOutcome:
        """Confirm and execute a staged command.

        Raises (fail-closed): ``UnknownConfirmationError`` (bad token),
        ``ForceConfirmationRequired`` (force command without ``force_ack``), or
        :class:`ArmBlockedError` (arm without a fresh arm-permitting health report).
        """
        spec = self._gate.confirm(token, force_ack=force_ack)
        if spec.name == "arm":
            report = self._health() if self._health is not None else None
            if not arm_allowed(report, self._clock.now(), self._settings.arm_report_max_age_s):
                self._audit.record("arm_blocked", {"id": token})
                raise ArmBlockedError("arm refused: no fresh arm-permitting health report")
        self._audit.record(
            "command_confirmed", {"id": token, "name": spec.name, "force_ack": force_ack}
        )
        return self._sender.execute(spec)
