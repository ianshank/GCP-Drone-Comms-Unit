"""Jetson helpers: pure ``tegrastats`` parsing + (hardware) power-mode controls.

:func:`parse_tegrastats` is pure and unit-tested. The functions that shell out to
``tegrastats`` / ``nvpmodel`` / ``jetson_clocks`` touch the device and are
``# pragma: no cover``.
"""

from __future__ import annotations

import re
import subprocess

_RAM_RE = re.compile(r"RAM (\d+)/(\d+)MB")
_GPU_RE = re.compile(r"GR3D_FREQ (\d+)%")
_TEMP_RE = re.compile(r"(\w+)@([\d.]+)C")


def parse_tegrastats(line: str) -> dict[str, float]:
    """Parse one ``tegrastats`` line into a flat metrics dict.

    Extracts RAM used/total (MB), GPU utilisation (%), and any ``<zone>@<temp>C``
    temperatures (as ``temp_<zone>``). Missing fields are simply omitted, so a
    partial or future-format line never raises.
    """
    metrics: dict[str, float] = {}
    ram = _RAM_RE.search(line)
    if ram:
        metrics["ram_used_mb"] = float(ram.group(1))
        metrics["ram_total_mb"] = float(ram.group(2))
    gpu = _GPU_RE.search(line)
    if gpu:
        metrics["gpu_pct"] = float(gpu.group(1))
    for zone, temp in _TEMP_RE.findall(line):
        metrics[f"temp_{zone.lower()}"] = float(temp)
    return metrics


def read_tegrastats(*, interval_ms: int = 1000) -> dict[str, float]:  # pragma: no cover - device
    """Sample one ``tegrastats`` line and parse it (requires a Jetson)."""
    proc = subprocess.run(
        ["tegrastats", "--interval", str(interval_ms), "--count", "1"],
        capture_output=True,
        text=True,
        check=True,
    )
    return parse_tegrastats(proc.stdout.strip())


def set_power_mode(mode: int) -> None:  # pragma: no cover - device
    """Set the Jetson power model via ``nvpmodel`` (requires root on a Jetson)."""
    subprocess.run(["nvpmodel", "-m", str(mode)], check=True)


def enable_jetson_clocks() -> None:  # pragma: no cover - device
    """Pin clocks to maximum via ``jetson_clocks`` (requires root on a Jetson)."""
    subprocess.run(["jetson_clocks"], check=True)
