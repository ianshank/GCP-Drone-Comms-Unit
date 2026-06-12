"""Dataset schema compatibility window (meshsa.fpv.version)."""

from __future__ import annotations

import warnings

import pytest

from meshsa.fpv import version as fv


def test_window_is_self_consistent():
    assert fv.MIN_COMPATIBLE_DATASET <= fv.DATASET_SCHEMA
    assert fv.SUPPORTED_DATASET_SCHEMAS == frozenset(
        range(fv.MIN_COMPATIBLE_DATASET, fv.DATASET_SCHEMA + 1)
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
    from meshsa import version as wire

    assert fv.DATASET_SCHEMA is not wire.SCHEMA_VERSION or fv is not wire


def test_warn_older_dataset_emits_dedicated_category():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        fv.warn_older_dataset(0)
    assert len(caught) == 1
    assert issubclass(caught[0].category, fv.DatasetCompatibilityWarning)
    # Distinct from DeprecationWarning so tools can filter exactly one.
    assert not issubclass(caught[0].category, DeprecationWarning)
