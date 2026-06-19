"""Bounded command set + allow-list (fakes-only; no link, no hardware)."""

import pytest

from meshsa.command import (
    CommanderSettings,
    CommandNotAllowedError,
    ForceDisarmDisabledError,
    UnknownCommandError,
    build_command,
)
from meshsa.command.commands import (
    FORCE_DISARM_MAGIC,
    MAV_CMD_COMPONENT_ARM_DISARM,
    MAV_CMD_DO_REPOSITION,
    MAV_CMD_DO_SET_MODE,
    MAV_CMD_NAV_RETURN_TO_LAUNCH,
    MAV_FRAME_GLOBAL_RELATIVE_ALT_INT,
)


def _settings(*names: str, force: bool = False) -> CommanderSettings:
    return CommanderSettings(allowed=frozenset(names), allow_force_disarm=force)


def test_default_allowlist_is_whitelist_first():
    s = CommanderSettings()
    assert s.allowed == frozenset({"set_mode", "rtl"})
    assert s.allow_force_disarm is False


def test_unknown_command_raises():
    with pytest.raises(UnknownCommandError):
        build_command("explode", CommanderSettings())


def test_known_but_not_allowed_raises():
    # arm exists but is not in the default allow-list.
    with pytest.raises(CommandNotAllowedError):
        build_command("arm", CommanderSettings())


def test_rtl_and_set_mode_are_allowed_by_default():
    rtl = build_command("rtl", CommanderSettings())
    assert rtl.command == MAV_CMD_NAV_RETURN_TO_LAUNCH
    assert rtl.kind == "long"

    sm = build_command("set_mode", CommanderSettings(), custom_mode=4)
    assert sm.command == MAV_CMD_DO_SET_MODE
    assert sm.params[0] == 1.0  # CUSTOM_MODE_ENABLED
    assert sm.params[1] == 4.0  # custom mode number


def test_arm_and_disarm_param1():
    arm = build_command("arm", _settings("arm"))
    disarm = build_command("disarm", _settings("disarm"))
    assert arm.command == MAV_CMD_COMPONENT_ARM_DISARM
    assert arm.params[0] == 1.0
    assert disarm.params[0] == 0.0
    assert arm.requires_force_confirm is False


def test_force_disarm_disabled_by_default_flag():
    # In the allow-list but the force flag is off -> refused.
    with pytest.raises(ForceDisarmDisabledError):
        build_command("force_disarm", _settings("force_disarm", force=False))


def test_force_disarm_enabled_sets_magic_and_force_flag():
    spec = build_command("force_disarm", _settings("force_disarm", force=True))
    assert spec.command == MAV_CMD_COMPONENT_ARM_DISARM
    assert spec.params[1] == FORCE_DISARM_MAGIC
    assert spec.requires_force_confirm is True


def test_goto_uses_command_int_with_dege7_scaling():
    spec = build_command("goto", _settings("goto"), lat_deg=37.7749, lon_deg=-122.4194, alt_m=30.0)
    assert spec.command == MAV_CMD_DO_REPOSITION
    assert spec.kind == "int"
    assert spec.frame == MAV_FRAME_GLOBAL_RELATIVE_ALT_INT
    assert spec.x == 377749000
    assert spec.y == -1224194000
    assert spec.z == 30.0
    assert spec.params[0] == -1.0  # default ground speed
