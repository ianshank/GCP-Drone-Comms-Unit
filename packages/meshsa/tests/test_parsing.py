"""Bounded numeric parsers name the offending field and range-check (fakes-only)."""

import pytest

from meshsa._parsing import parse_float, parse_int


def test_parse_int_ok_and_coerces_strings():
    assert parse_int("X", "42") == 42
    assert parse_int("X", 42) == 42


def test_parse_int_bad_value_names_the_field():
    with pytest.raises(ValueError, match="MESHSA_PORTNUM: expected an integer, got 'nope'"):
        parse_int("MESHSA_PORTNUM", "nope")


def test_parse_int_range_messages():
    with pytest.raises(ValueError, match="below the minimum 1"):
        parse_int("port", 0, lo=1, hi=65535)
    with pytest.raises(ValueError, match="above the maximum 65535"):
        parse_int("port", 70000, lo=1, hi=65535)
    assert parse_int("port", 8090, lo=1, hi=65535) == 8090


def test_parse_float_ok_and_errors():
    assert parse_float("X", "1.5") == 1.5
    with pytest.raises(ValueError, match="lat: expected a number, got 'NaNsense'"):
        parse_float("lat", "NaNsense")
    with pytest.raises(ValueError, match="below the minimum"):
        parse_float("interval", -1.0, lo=0.0)
