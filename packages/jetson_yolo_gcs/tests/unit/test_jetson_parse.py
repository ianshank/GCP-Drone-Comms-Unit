"""tegrastats line parsing (pure half of utils/jetson.py)."""

from __future__ import annotations

from jetson_yolo_gcs.utils.jetson import parse_tegrastats

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
