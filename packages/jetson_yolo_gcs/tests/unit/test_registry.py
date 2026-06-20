"""Registry behaviour: register, create, has/available, error paths."""

from __future__ import annotations

import pytest

from jetson_yolo_gcs.core.errors import (
    DuplicateRegistrationError,
    UnknownComponentError,
)
from jetson_yolo_gcs.core.registry import Registry


def test_register_create_and_introspect() -> None:
    reg: Registry[str] = Registry("thing")

    @reg.register("a")
    def _make_a() -> str:
        return "A"

    assert reg.has("a")
    assert reg.available() == ["a"]
    assert reg.create("a") == "A"


def test_duplicate_registration_raises() -> None:
    reg: Registry[str] = Registry("thing")

    @reg.register("a")
    def _make_a() -> str:
        return "A"

    with pytest.raises(DuplicateRegistrationError):

        @reg.register("a")
        def _make_a2() -> str:
            return "A2"


def test_unknown_component_raises() -> None:
    reg: Registry[str] = Registry("thing")
    with pytest.raises(UnknownComponentError):
        reg.create("missing")
