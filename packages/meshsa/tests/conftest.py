import itertools

import pytest


class FakeClock:
    def __init__(self, start: float = 1_000.0) -> None:
        self._t = start

    def now(self) -> float:
        self._t += 1.0
        return self._t


class SeqIdFactory:
    def __init__(self) -> None:
        self._c = itertools.count(1)

    def new_id(self) -> str:
        return f"id-{next(self._c)}"


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def ids() -> SeqIdFactory:
    return SeqIdFactory()
