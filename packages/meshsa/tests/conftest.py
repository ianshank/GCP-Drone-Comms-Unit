import itertools
from collections.abc import Mapping
from typing import Any

import pytest

from meshsa import HttpResponse


class FakeHttpTransport:
    """Scriptable :class:`meshsa.HttpTransport` for tests — no aiohttp, no sockets.

    Construct with an ordered list of *responses*; each is either an
    :class:`meshsa.HttpResponse` (returned) or an ``Exception`` (raised) — the
    latter models a transport-level failure. Calls are recorded on ``.calls`` so
    tests can assert request shape and retry counts. Set ``repeat_last`` when the
    number of calls is not deterministic (e.g. the e2e wiring test).
    """

    def __init__(
        self,
        responses: list[HttpResponse | Exception] | None = None,
        *,
        repeat_last: bool = False,
    ) -> None:
        self._responses: list[HttpResponse | Exception] = list(responses or [])
        self._repeat_last = repeat_last
        self.calls: list[dict[str, Any]] = []
        self.closed = False

    async def post_json(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        json_body: Mapping[str, Any],
        timeout_s: float,
    ) -> HttpResponse:
        self.calls.append(
            {
                "url": url,
                "headers": dict(headers),
                "json_body": dict(json_body),
                "timeout_s": timeout_s,
            }
        )
        if not self._responses:
            raise AssertionError("FakeHttpTransport ran out of scripted responses")
        item = (
            self._responses[0]
            if self._repeat_last and len(self._responses) == 1
            else self._responses.pop(0)
        )
        if isinstance(item, Exception):
            raise item
        return item

    async def aclose(self) -> None:
        self.closed = True


def ok(content: str) -> HttpResponse:
    """A 200 response shaped like the NIM chat-completions payload."""
    return HttpResponse(status=200, payload={"choices": [{"message": {"content": content}}]})


@pytest.fixture
def make_transport():
    """Return the :class:`FakeHttpTransport` factory for ad-hoc construction."""
    return FakeHttpTransport


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
