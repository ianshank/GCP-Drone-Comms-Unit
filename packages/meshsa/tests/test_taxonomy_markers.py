"""Pins for the unit/integration taxonomy markers applied by ``conftest.py`` (plan P1-5)."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import _INTEGRATION_STEMS, is_integration_test_path

_TESTS_DIR = Path(__file__).parent

#: Files docs/LOCAL_TESTING_PLAN.md names in its Integration / E2E / Soak rows.
_PLAN_INTEGRATION_FILES = (
    "test_tak.py",
    "test_mavlink_source.py",
    "test_scout_station.py",
    "test_ui_app.py",
    "test_detection_e2e.py",
    "test_inference_e2e.py",
    "test_link_loss_soak.py",
    "test_detection_ingest.py",  # real loopback UDP socket
)
_PLAN_UNIT_FILES = ("test_pacing.py", "test_netauth.py", "test_compact.py", "test_router.py")


def test_every_exact_stem_in_the_list_names_a_real_file() -> None:
    # A stale entry would silently stop selecting anything.
    missing = sorted(
        stem for stem in _INTEGRATION_STEMS if not (_TESTS_DIR / f"{stem}.py").is_file()
    )
    assert missing == []


@pytest.mark.parametrize("name", _PLAN_INTEGRATION_FILES)
def test_plan_integration_files_are_integration(name: str) -> None:
    assert is_integration_test_path(_TESTS_DIR / name, _TESTS_DIR.parent)


@pytest.mark.parametrize("name", _PLAN_UNIT_FILES)
def test_plan_unit_files_are_unit(name: str) -> None:
    assert not is_integration_test_path(_TESTS_DIR / name, _TESTS_DIR.parent)


@pytest.mark.parametrize("name", ["test_append.py", "test_take_two.py", "test_apply.py"])
def test_matching_is_exact_not_substring(name: str) -> None:
    assert not is_integration_test_path(_TESTS_DIR / name, _TESTS_DIR.parent)


def test_e2e_directory_is_judged_relative_to_the_rootdir(tmp_path: Path) -> None:
    rootdir = tmp_path / "e2e" / "pkg"
    assert not is_integration_test_path(rootdir / "tests" / "test_pacing.py", rootdir)
    assert is_integration_test_path(rootdir / "tests" / "e2e" / "test_x.py", rootdir)


def test_every_collected_item_has_exactly_one_taxonomy_marker(
    request: pytest.FixtureRequest,
) -> None:
    for item in request.session.items:
        names = {mark.name for mark in item.iter_markers()}
        assert ("unit" in names) ^ ("integration" in names), item.nodeid


def test_marker_hook_ignores_directories_above_the_rootdir(tmp_path: Path) -> None:
    """Regression: the first version tested ``item.path.parts`` (absolute), so a checkout
    under a directory named ``e2e`` marked every test integration and ``-m unit``
    collected nothing. Run the real conftest in a throwaway package under such a path."""
    pkg = tmp_path / "e2e" / "pkg"
    (pkg / "tests").mkdir(parents=True)
    shutil.copy(_TESTS_DIR / "conftest.py", pkg / "tests" / "conftest.py")
    (pkg / "tests" / "test_pacing.py").write_text("def test_x() -> None:\n    pass\n")
    (pkg / "pyproject.toml").write_text(
        '[tool.pytest.ini_options]\nmarkers = ["unit: u", "integration: i", "slow: s", "e2e: e"]\n'
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
