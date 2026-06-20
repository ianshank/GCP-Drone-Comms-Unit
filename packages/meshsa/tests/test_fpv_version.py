"""Dataset schema compatibility window (meshsa.fpv.version)."""

from __future__ import annotations

import warnings

import pytest

from meshsa.fpv import version as fv


def test_window_is_self_consistent():
    assert fv.MIN_COMPATIBLE_DATASET <= fv.DATASET_SCHEMA
    assert (
        frozenset(range(fv.MIN_COMPATIBLE_DATASET, fv.DATASET_SCHEMA + 1))
        == fv.SUPPORTED_DATASET_SCHEMAS
    )


@pytest.mark.parametrize("v", sorted(fv.SUPPORTED_DATASET_SCHEMAS))
def test_supported_schemas_are_compatible(v):
    assert fv.is_dataset_compatible(v)


@pytest.mark.parametrize("v", [fv.MIN_COMPATIBLE_DATASET - 1, fv.DATASET_SCHEMA + 1])
def test_out_of_window_is_incompatible(v):
    assert not fv.is_dataset_compatible(v)


def test_dataset_schema_decoupled_from_wire_schema():
    # The dataset schema is its own namespace; it must not alias the meshsa wire
    # SCHEMA_VERSION (a logger format change must never bump the wire window).
    # NB: `is` on ints is meaningless here (CPython interns small ints), so this
    # validates by module identity + which constant governs the dataset window.
    from meshsa import version as wire

    # Both are plain module-level ints living in two *different* modules.
    assert isinstance(fv.DATASET_SCHEMA, int)
    assert isinstance(wire.SCHEMA_VERSION, int)
    assert fv is not wire
    assert fv.__name__ != wire.__name__

    # The fpv dataset compatibility window is governed by the fpv constants, not
    # the wire constant. If someone aliased `DATASET_SCHEMA = wire.SCHEMA_VERSION`,
    # the window's upper bound would track the wire value and this would fail.
    assert max(fv.SUPPORTED_DATASET_SCHEMAS) == fv.DATASET_SCHEMA
    assert min(fv.SUPPORTED_DATASET_SCHEMAS) == fv.MIN_COMPATIBLE_DATASET
    assert fv.is_dataset_compatible(fv.DATASET_SCHEMA)
    # The dataset window must extend beyond the wire window's single value here;
    # an alias would collapse DATASET_SCHEMA back onto wire.SCHEMA_VERSION.
    assert fv.DATASET_SCHEMA != wire.SCHEMA_VERSION


def test_warn_older_dataset_emits_dedicated_category():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        fv.warn_older_dataset(0)
    assert len(caught) == 1
    assert issubclass(caught[0].category, fv.DatasetCompatibilityWarning)
    # Distinct from DeprecationWarning so tools can filter exactly one.
    assert not issubclass(caught[0].category, DeprecationWarning)
