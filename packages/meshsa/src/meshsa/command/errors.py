"""Typed errors for the supervised command path.

All inherit :class:`CommandError` so a caller (the HTTP endpoint) can map the
whole family to a refusal without catching ``Exception``. Every refusal here is
**fail-closed**: it prevents a command from being staged, confirmed, or sent.
"""

from __future__ import annotations


class CommandError(Exception):
    """Base class for every supervised-command refusal."""


class UnknownCommandError(CommandError):
    """Requested a command name with no builder (not part of the bounded set)."""


class CommandNotAllowedError(CommandError):
    """The command is known but not in the configured allow-list (whitelist-first)."""


class ForceDisarmDisabledError(CommandError):
    """Force-disarm was requested while ``allow_force_disarm`` is off (the default)."""


class UnknownConfirmationError(CommandError):
    """Confirmed a token that was never staged, already consumed, or cancelled."""


class ForceConfirmationRequired(CommandError):
    """A force command was confirmed without its distinct force acknowledgement.

    Raised so a normal per-command confirmation can **never** satisfy the
    force-disarm path (design §5). The staged command is left intact so a proper
    force-confirmation can still release it.
    """


class ArmBlockedError(CommandError):
    """Arm refused by the pre-arm interlock: no fresh, arm-permitting health report.

    Fail-closed (design §4d): an arm command is never sent unless a recent
    :class:`~meshsa.fpv.link_health.HealthReport` says arming is permitted.
    """
