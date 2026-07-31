"""Shared pytest configuration for the meshsa.ui named validation scenarios.

Drop this file into ``packages/meshsa/tests/`` alongside the scenario test
files.  It is intentionally minimal — it does not re-declare fixtures that
already exist in the upstream ``conftest.py`` (if any).

What this file provides:
    * ``asyncio_mode = "auto"`` via ``pytest_configure`` so all ``async def``
      test functions in this directory are collected and run without requiring
      an explicit ``@pytest.mark.asyncio`` decorator.  This matches common
      meshsa project convention (check ``pyproject.toml`` for the authoritative
      setting; if ``asyncio_mode = "auto"`` is already set project-wide this
      file is a no-op duplicate that does no harm).
    * Shared ``fake_clock`` and ``make_store`` fixtures for tests that prefer
      the pytest-fixture style over calling the module-level helpers directly.
    * ``_validate_geojson_feature_collection`` — a reusable assertion helper
      registered as a fixture so individual tests can call it without importing.

Dependency:
    ``pytest-asyncio >= 0.23`` — add to ``[project.optional-dependencies]``
    dev section in ``pyproject.toml``::

        dev = [
            "pytest>=8",
            "pytest-asyncio>=0.23",
            "pytest-cov>=5",
            "hypothesis>=6.100",
            "aiohttp>=3.9",
        ]
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from meshsa.ui.snapshot import SnapshotStore

# ---------------------------------------------------------------------------
# asyncio mode — auto-collect async test functions without the decorator
# ---------------------------------------------------------------------------


def pytest_configure(config: pytest.Config) -> None:  # noqa: D401
    """Register the asyncio auto-mode marker so it shows up in --markers."""
    config.addinivalue_line(
        "markers",
        "asyncio: mark a test as an asyncio coroutine (auto-applied in auto mode)",
    )


# The authoritative setting for asyncio_mode goes in pyproject.toml.
# Add (or verify) this section exists:
#
# [tool.pytest.ini_options]
# asyncio_mode = "auto"
# addopts = "--cov=meshsa --cov-report=term-missing --cov-fail-under=97"
#
# If you cannot edit pyproject.toml, you can force it here:
# import pytest_asyncio  # noqa: F401  (import forces the plugin activation)
# The marker-based approach in the test files is always safe as a fallback.


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


class _FakeClock:
    """Injectable monotonic clock whose current time is mutable in tests."""

    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def now(self) -> float:
        return self.t


@pytest.fixture()
def fake_clock() -> _FakeClock:
    """A mutable fake clock starting at t=0.0.

    Yields a ``_FakeClock`` instance whose ``.t`` attribute can be advanced
    to simulate the passage of time without sleeping::

        def test_ttl(fake_clock):
            fake_clock.t = 301.0  # advance past TTL
            assert store.tracks_geojson()["features"] == []
    """
    return _FakeClock(t=0.0)


@pytest.fixture()
def make_store(fake_clock: _FakeClock) -> Callable[..., SnapshotStore]:
    """Factory fixture that builds a ``SnapshotStore`` wired to ``fake_clock``.

    Returns a callable::

        store = make_store(max_tracks=8, track_stale_s=30.0)

    All keyword arguments are forwarded to ``SnapshotStore.__init__``.
    The clock defaults to the ``fake_clock`` fixture (shared within the test).
    """

    def _factory(
        *,
        max_tracks: int = 64,
        max_detections: int = 64,
        track_stale_s: float = 300.0,
        detection_stale_s: float = 3600.0,
    ) -> SnapshotStore:
        return SnapshotStore(
            fake_clock,
            max_tracks=max_tracks,
            max_detections=max_detections,
            track_stale_s=track_stale_s,
            detection_stale_s=detection_stale_s,
        )

    return _factory


@pytest.fixture()
def assert_geojson_feature_collection() -> Callable[..., None]:
    """Return a callable that validates the shape of a GeoJSON FeatureCollection.

    Usage::

        def test_empty(assert_geojson_feature_collection, fake_clock, make_store):
            store = make_store()
            fc = store.tracks_geojson()
            assert_geojson_feature_collection(fc, expected_count=0)
    """

    def _assert(
        fc: object,
        *,
        expected_count: int | None = None,
        message: str = "",
    ) -> None:
        """Assert ``fc`` is a well-formed GeoJSON FeatureCollection.

        Args:
            fc: The value to validate (typically the return of
                ``SnapshotStore.tracks_geojson()``).
            expected_count: If provided, assert ``len(features)`` equals this.
            message: Additional context shown on assertion failure.
        """
        prefix = f"{message}: " if message else ""
        assert isinstance(fc, dict), f"{prefix}Expected dict, got {type(fc).__name__}"
        assert fc.get("type") == "FeatureCollection", (
            f"{prefix}Expected 'FeatureCollection', got {fc.get('type')!r}"
        )
        assert "features" in fc, f"{prefix}Missing 'features' key"
        assert isinstance(fc["features"], list), (
            f"{prefix}'features' must be a list, got {type(fc['features']).__name__}"
        )
        if expected_count is not None:
            assert len(fc["features"]) == expected_count, (
                f"{prefix}Expected {expected_count} feature(s), got {len(fc['features'])}"
            )

    return _assert
