"""The bounded command set and the allow-list that gates it.

A :class:`CommandSpec` is a pure, transport-agnostic description of one MAVLink
command. It deliberately holds **no live link**: per the §10 amendment, the live
``MAVLink`` instance packs/signs the wire frame in the link layer, because pymavlink
encoding needs the connection's sequence counter and signing state. The MAV_*
integer constants are inlined (mirroring the MAVLink ``common`` dialect) so this
module stays dependency-free and fakes-testable.

Commands are introduced in **risk order** (design §7): ``set_mode`` and ``rtl``
are in the default allow-list; arm/disarm and the positional ``goto`` are opt-in;
``force_disarm`` is gated by a separate flag *and* a separate confirmation.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from .errors import (
    CommandNotAllowedError,
    ForceDisarmDisabledError,
    UnknownCommandError,
)

# --- MAVLink common-dialect constants (inlined to keep this module pure) ------
MAV_CMD_NAV_RETURN_TO_LAUNCH = 20
MAV_CMD_DO_SET_MODE = 176
MAV_CMD_DO_REPOSITION = 192
MAV_CMD_COMPONENT_ARM_DISARM = 400

MAV_MODE_FLAG_CUSTOM_MODE_ENABLED = 1
MAV_FRAME_GLOBAL_RELATIVE_ALT_INT = 6

#: Magic ``param2`` that turns ARM_DISARM into an interlock-bypassing **force**
#: path (forces an in-flight disarm → motors off). The single most dangerous value
#: in the set; only ever produced by :func:`_force_disarm` (design §5).
FORCE_DISARM_MAGIC = 21196.0

#: degE7 scaling for COMMAND_INT positional fields (lat/lon as scaled integers).
_DEGE7 = 1e7

_NO_PARAMS: tuple[float, ...] = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)


@dataclass(frozen=True)
class CommandSpec:
    """A pure description of one MAVLink command, ready for the link layer to pack.

    ``kind`` selects the wire message: ``"long"`` uses all seven ``params``;
    ``"int"`` uses ``params[0:4]`` plus the scaled-integer ``x``/``y`` and float
    ``z`` with ``frame``.
    """

    name: str
    command: int
    kind: str  # "long" | "int"
    params: tuple[float, ...] = _NO_PARAMS
    frame: int = 0
    x: int = 0
    y: int = 0
    z: float = 0.0
    #: True only for force-disarm: requires a distinct force confirmation (§5).
    requires_force_confirm: bool = False


@dataclass(frozen=True)
class CommanderSettings:
    """Config-driven policy (no magic numbers; explicit defaults).

    The default allow-list is **whitelist-first**: only the low-risk, recoverable
    commands are enabled out of the box. Arm/disarm and ``goto`` must be opted in.
    """

    allowed: frozenset[str] = field(default_factory=lambda: frozenset({"set_mode", "rtl"}))
    allow_force_disarm: bool = False
    ack_timeout_s: float = 2.0
    max_attempts: int = 3
    arm_report_max_age_s: float = 2.0


# --- builders ----------------------------------------------------------------
def _arm() -> CommandSpec:
    return CommandSpec(
        name="arm",
        command=MAV_CMD_COMPONENT_ARM_DISARM,
        kind="long",
        params=(1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
    )


def _disarm() -> CommandSpec:
    return CommandSpec(
        name="disarm",
        command=MAV_CMD_COMPONENT_ARM_DISARM,
        kind="long",
        params=(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
    )


def _force_disarm() -> CommandSpec:
    return CommandSpec(
        name="force_disarm",
        command=MAV_CMD_COMPONENT_ARM_DISARM,
        kind="long",
        params=(0.0, FORCE_DISARM_MAGIC, 0.0, 0.0, 0.0, 0.0, 0.0),
        requires_force_confirm=True,
    )


def _rtl() -> CommandSpec:
    return CommandSpec(
        name="rtl",
        command=MAV_CMD_NAV_RETURN_TO_LAUNCH,
        kind="long",
        params=_NO_PARAMS,
    )


def _set_mode(custom_mode: int) -> CommandSpec:
    """Switch flight mode via DO_SET_MODE (custom-mode path).

    ``param1`` carries the base-mode flag enabling a custom mode; ``param2`` is the
    autopilot-specific mode number (e.g. ArduCopter GUIDED=4, RTL=6).
    """
    return CommandSpec(
        name="set_mode",
        command=MAV_CMD_DO_SET_MODE,
        kind="long",
        params=(
            float(MAV_MODE_FLAG_CUSTOM_MODE_ENABLED),
            float(custom_mode),
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
        ),
    )


def _goto(lat_deg: float, lon_deg: float, alt_m: float) -> CommandSpec:
    """Reposition to a global lat/lon/alt via DO_REPOSITION (COMMAND_INT, guided).

    Positional fields use COMMAND_INT scaled integers (degE7) to avoid the
    float-precision loss COMMAND_LONG would impose on geographic params (design §3).
    ``param1=-1`` keeps the default ground speed; ``param4`` (yaw) is left 0.
    """
    return CommandSpec(
        name="goto",
        command=MAV_CMD_DO_REPOSITION,
        kind="int",
        params=(-1.0, 0.0, 0.0, 0.0),
        frame=MAV_FRAME_GLOBAL_RELATIVE_ALT_INT,
        x=int(round(lat_deg * _DEGE7)),
        y=int(round(lon_deg * _DEGE7)),
        z=alt_m,
    )


#: name -> builder. Builders take only their own positional params (validated by
#: :func:`build_command` before dispatch).
_BUILDERS: dict[str, Callable[..., CommandSpec]] = {
    "arm": _arm,
    "disarm": _disarm,
    "force_disarm": _force_disarm,
    "rtl": _rtl,
    "set_mode": _set_mode,
    "goto": _goto,
}


def build_command(name: str, settings: CommanderSettings, **params: float) -> CommandSpec:
    """Build a :class:`CommandSpec`, enforcing the allow-list and force flag.

    Raises (all fail-closed, all :class:`~meshsa.command.errors.CommandError`):

    * :class:`UnknownCommandError` — no builder for ``name``.
    * :class:`CommandNotAllowedError` — ``name`` not in ``settings.allowed``.
    * :class:`ForceDisarmDisabledError` — ``force_disarm`` while the flag is off.

    Builder ``**params`` (e.g. ``goto(lat_deg=..., lon_deg=..., alt_m=...)``) are
    forwarded as-is; a bad kwarg surfaces as a ``TypeError`` from the builder.
    """
    builder = _BUILDERS.get(name)
    if builder is None:
        raise UnknownCommandError(name)
    if name not in settings.allowed:
        raise CommandNotAllowedError(name)
    if name == "force_disarm" and not settings.allow_force_disarm:
        raise ForceDisarmDisabledError(name)
    return builder(**params)
