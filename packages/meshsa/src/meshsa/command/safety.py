"""The supervisory gates: per-command confirmation + the pre-arm interlock predicate.

Two independent safety controls live here:

* :func:`arm_allowed` — the freshness/``arm_permitted`` predicate extracted from
  ``ArmGuard._arm_allowed``. We reuse only this ~3-line predicate, **not** the RC
  ``ArmGuard`` itself (it clamps PWM channels and has no COMMAND_LONG arm path; see
  design §10). It gives **no** in-flight backstop against force-disarm.
* :class:`ConfirmationGate` — every command must be staged, then explicitly
  confirmed, before the caller can obtain the :class:`CommandSpec` to send. An
  unconfirmed command is structurally impossible to transmit (you can only send
  what :meth:`ConfirmationGate.confirm` returns). Force commands need a *distinct*
  force acknowledgement, which a normal confirmation can never supply (design §5).
"""

from __future__ import annotations

from ..fpv.link_health import HealthReport
from ..protocols import IdFactory
from .commands import CommandSpec
from .errors import ForceConfirmationRequired, UnknownConfirmationError


def arm_allowed(report: HealthReport | None, now: float, max_age_s: float) -> bool:
    """True only when a fresh, arm-permitting health report backs the arm.

    Mirrors ``ArmGuard._arm_allowed``: no report → not allowed; a stale report
    (older than ``max_age_s`` on the same timebase as ``now``) → not allowed;
    otherwise gated on ``report.arm_permitted``.
    """
    if report is None:
        return False
    return (now - report.t_mono) <= max_age_s and report.arm_permitted


class ConfirmationGate:
    """Stage-then-confirm gate enforcing per-command human confirmation (§4a).

    Not internally synchronized — drive it from a single thread (or serialize),
    matching the rest of the supervised service.
    """

    def __init__(self, id_factory: IdFactory) -> None:
        self._id = id_factory
        self._pending: dict[str, CommandSpec] = {}

    def stage(self, spec: CommandSpec) -> str:
        """Stage ``spec`` for confirmation; return the confirmation token."""
        token = self._id.new_id()
        self._pending[token] = spec
        return token

    def pending(self, token: str) -> CommandSpec:
        """Peek a staged command without consuming it (for an operator preview)."""
        try:
            return self._pending[token]
        except KeyError as exc:
            raise UnknownConfirmationError(token) from exc

    def confirm(self, token: str, *, force_ack: bool = False) -> CommandSpec:
        """Consume a staged command and return it for sending.

        Raises :class:`UnknownConfirmationError` for an unknown/already-consumed
        token. For a force command, raises :class:`ForceConfirmationRequired`
        unless ``force_ack`` is True — and **leaves the command staged** so a
        proper force-confirmation can still release it (the normal confirm did not
        consume it).
        """
        if token not in self._pending:
            raise UnknownConfirmationError(token)
        spec = self._pending[token]
        if spec.requires_force_confirm and not force_ack:
            raise ForceConfirmationRequired(spec.name)
        del self._pending[token]
        return spec

    def cancel(self, token: str) -> None:
        """Discard a staged command (idempotent: unknown tokens are ignored)."""
        self._pending.pop(token, None)
