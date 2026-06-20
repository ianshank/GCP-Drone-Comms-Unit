"""Open/closed component registry (mirrors ``meshsa.registry``).

New detection backends register themselves here, so adding a backend never requires
editing the factory or pipeline (forward/backward compatible by construction).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Generic, TypeVar

from .errors import DuplicateRegistrationError, UnknownComponentError

T = TypeVar("T")


class Registry(Generic[T]):
    """A name -> factory map with decorator registration."""

    def __init__(self, kind: str) -> None:
        self._kind = kind
        self._factories: dict[str, Callable[..., T]] = {}

    def register(self, name: str) -> Callable[[Callable[..., T]], Callable[..., T]]:
        def decorator(factory: Callable[..., T]) -> Callable[..., T]:
            if name in self._factories:
                raise DuplicateRegistrationError(f"{self._kind} {name!r} already registered")
            self._factories[name] = factory
            return factory

        return decorator

    def create(self, key: str, **kwargs: object) -> T:
        try:
            factory = self._factories[key]
        except KeyError as exc:
            raise UnknownComponentError(f"no {self._kind} named {key!r}") from exc
        return factory(**kwargs)

    def has(self, name: str) -> bool:
        return name in self._factories

    def available(self) -> list[str]:
        return sorted(self._factories)
