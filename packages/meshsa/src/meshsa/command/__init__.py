"""Supervised two-way MAVLink commanding (Initiative C).

This package is the **standalone supervised command path** described in
``docs/specs/initiative-c-commanding-design.md`` §10 (proposed amendment):
commands do **not** become :class:`meshsa.models.Envelope` and do **not** traverse
:class:`meshsa.router.Router`. The pieces here are pure-Python and hardware-free
(fakes-only tests); the live pymavlink link + HTTP control endpoint are wired in
``flightctl/run_commander.py`` and are the only ``# pragma: no cover`` glue.

Nothing in this package transmits a command on its own: a :class:`CommandSpec`
must pass the :class:`ConfirmationGate` and the :class:`CommandSender` lifecycle
(ACK/retry/timeout, fail-closed) before a :class:`CommandLink` ever sees it.
"""

from __future__ import annotations

from .audit import JsonlAuditLog
from .commands import (
    CommanderSettings,
    CommandSpec,
    build_command,
)
from .errors import (
    ArmBlockedError,
    CommandError,
    CommandNotAllowedError,
    ForceConfirmationRequired,
    ForceDisarmDisabledError,
    UnknownCommandError,
    UnknownConfirmationError,
)
from .health import HeartbeatHealth
from .lifecycle import (
    Ack,
    AuditLog,
    CommandLink,
    CommandOutcome,
    CommandSender,
)
from .mavlink_link import MavlinkCommandLink
from .safety import ConfirmationGate, arm_allowed
from .service import CommandService, HealthProvider, StagedCommand

__all__ = [
    "Ack",
    "ArmBlockedError",
    "AuditLog",
    "CommanderSettings",
    "CommandError",
    "CommandLink",
    "CommandNotAllowedError",
    "CommandOutcome",
    "CommandSender",
    "CommandService",
    "CommandSpec",
    "ConfirmationGate",
    "ForceConfirmationRequired",
    "ForceDisarmDisabledError",
    "HealthProvider",
    "HeartbeatHealth",
    "JsonlAuditLog",
    "MavlinkCommandLink",
    "StagedCommand",
    "UnknownCommandError",
    "UnknownConfirmationError",
    "arm_allowed",
    "build_command",
]
