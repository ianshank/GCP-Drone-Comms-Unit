"""tegrastats line parsing + config wiring (pure half of utils/jetson.py).

The device shell-out functions (``read_tegrastats``/``set_power_mode``/``enable_jetson_clocks``)
are ``# pragma: no cover`` (they touch real hardware), but their *default values* are pure data
sourced from :class:`JetsonSettings` and are unit-tested here without ever invoking
``subprocess``.
"""

from __future__ import annotations

from jetson_yolo_gcs.core.config import JetsonSettings
from jetson_yolo_gcs.utils.jetson import (
    _DEFAULT_TEGRASTATS_INTERVAL_MS,
    _SUBPROCESS_TIMEOUT_S,
    enable_jetson_clocks,
    parse_tegrastats,
    read_tegrastats,
    set_power_mode,
)

_SAMPLE = (
    "RAM 2954/7765MB (lfb 4x256kB) SWAP 0/3882MB (cached 0MB) "
    "CPU [12%@1479,5%@1479,off,off] GR3D_FREQ 27% "
    "CPU@45.5C GPU@44C thermal@44.75C"
)


def test_parses_ram_gpu_and_temps() -> None:
    m = parse_tegrastats(_SAMPLE)
    assert m["ram_used_mb"] == 2954.0
    assert m["ram_total_mb"] == 7765.0
    assert m["gpu_pct"] == 27.0
    assert m["temp_cpu"] == 45.5
    assert m["temp_gpu"] == 44.0
    assert m["temp_thermal"] == 44.75


def test_partial_line_never_raises() -> None:
    assert parse_tegrastats("garbage with no fields") == {}


def test_module_defaults_match_jetson_settings() -> None:
    # Single source of truth: the module-level defaults must mirror JetsonSettings so a bare
    # call and any future settings-driven caller never diverge (charter Invariant 5).
    settings = JetsonSettings()
    assert _SUBPROCESS_TIMEOUT_S == settings.subprocess_timeout_s == 10.0
    assert _DEFAULT_TEGRASTATS_INTERVAL_MS == settings.tegrastats_interval_ms == 1000


def test_read_tegrastats_bare_defaults_source_from_settings() -> None:
    # Both keyword-only params' bare defaults must equal JetsonSettings(), not an independent
    # hardcoded literal — proven via the live function signature, not a duplicated constant.
    defaults = read_tegrastats.__kwdefaults__
    assert defaults is not None
    settings = JetsonSettings()
    assert defaults["interval_ms"] == settings.tegrastats_interval_ms
    assert defaults["timeout_s"] == settings.subprocess_timeout_s


def test_set_power_mode_bare_default_sources_from_settings() -> None:
    defaults = set_power_mode.__kwdefaults__
    assert defaults is not None
    assert defaults["timeout_s"] == JetsonSettings().subprocess_timeout_s


def test_enable_jetson_clocks_bare_default_sources_from_settings() -> None:
    defaults = enable_jetson_clocks.__kwdefaults__
    assert defaults is not None
    assert defaults["timeout_s"] == JetsonSettings().subprocess_timeout_s
