"""Pins for the unit/integration taxonomy markers applied by ``tests/conftest.py`` (plan P1-5)."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).parent.parent


def test_every_collected_item_has_exactly_one_taxonomy_marker(
    request: pytest.FixtureRequest,
) -> None:
    for item in request.session.items:
        names = {mark.name for mark in item.iter_markers()}
        assert ("unit" in names) ^ ("integration" in names), item.nodeid


def test_marker_hook_ignores_directories_above_the_rootdir(tmp_path: Path) -> None:
    """Regression: judging the absolute path marked every test integration when the
    checkout lived under a directory named ``integration``, and ``-m unit`` collected
    nothing. Run the real conftest in a throwaway package under such a path."""
    pkg = tmp_path / "integration" / "pkg"
    (pkg / "tests" / "unit").mkdir(parents=True)
    shutil.copy(_TESTS_DIR / "conftest.py", pkg / "tests" / "conftest.py")
    (pkg / "tests" / "unit" / "test_x.py").write_text("def test_x() -> None:\n    pass\n")
    (pkg / "pyproject.toml").write_text(
        '[tool.pytest.ini_options]\nmarkers = ["unit: u", "integration: i"]\n'
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-m",
            "unit",
            "--co",
            "-q",
            "-p",
            "no:cacheprovider",
            "tests",
        ],
        cwd=pkg,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 test collected" in result.stdout, result.stdout
