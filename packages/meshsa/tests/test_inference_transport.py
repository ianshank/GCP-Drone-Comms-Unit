"""``meshsa.inference.transport`` tests: AiohttpTransport session-reuse + error
mapping (no real sockets), and the ``_require_aiohttp`` optional-dependency guard.

A fake aiohttp-style session covers the transport logic that would otherwise
only run against a live socket. Only real ``aiohttp.ClientSession`` creation
stays ``# pragma: no cover``.
"""

import asyncio

import pytest

import meshsa.inference.transport as inference_transport_mod
from meshsa import AiohttpTransport, InferenceTransportError
from meshsa.inference.transport import _require_aiohttp


class _FakeResp:
    def __init__(self, status, body, *, json_exc=None):
        self.status = status
        self._body = body
        self._json_exc = json_exc

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def json(self):
        if self._json_exc is not None:
            raise self._json_exc
        return self._body


class _FakeSession:
    def __init__(self, responses=None, *, post_exc=None):
        self._responses = list(responses or [])
        self._post_exc = post_exc
        self.closed = False
        self.post_calls = 0

    def post(self, url, **kwargs):
        self.post_calls += 1
        if self._post_exc is not None:
            raise self._post_exc
        return self._responses.pop(0)

    async def close(self):
        self.closed = True


class _SessionFactory:
    def __init__(self, sessions):
        self._sessions = list(sessions)
        self.created = 0

    def __call__(self):
        self.created += 1
        return self._sessions.pop(0)


async def _post(transport):
    return await transport.post_json(
        "https://x/v1/chat/completions", headers={"h": "v"}, json_body={"k": "v"}, timeout_s=1.0
    )


async def test_aiohttp_transport_success_and_session_reuse():
    session = _FakeSession([_FakeResp(200, {"ok": 1}), _FakeResp(200, {"ok": 2})])
    factory = _SessionFactory([session])
    transport = AiohttpTransport(session_factory=factory)

    r1 = await _post(transport)
    r2 = await _post(transport)
    assert (r1.status, r1.payload) == (200, {"ok": 1})
    assert r2.payload == {"ok": 2}
    assert factory.created == 1  # session reused across calls
    assert session.post_calls == 2


async def test_aiohttp_transport_json_parse_fallback():
    session = _FakeSession([_FakeResp(200, None, json_exc=ValueError("not json"))])
    transport = AiohttpTransport(session_factory=_SessionFactory([session]))
    r = await _post(transport)
    assert r.payload == {}  # unparseable body degrades to empty dict, not a crash


async def test_aiohttp_transport_non_dict_body_becomes_empty():
    session = _FakeSession([_FakeResp(200, ["not", "a", "dict"])])
    transport = AiohttpTransport(session_factory=_SessionFactory([session]))
    r = await _post(transport)
    assert r.payload == {}


async def test_aiohttp_transport_maps_timeout_to_transport_error():
    session = _FakeSession(post_exc=asyncio.TimeoutError())
    transport = AiohttpTransport(session_factory=_SessionFactory([session]))
    with pytest.raises(InferenceTransportError):
        await _post(transport)


async def test_aiohttp_transport_maps_client_error_to_transport_error():
    import aiohttp

    session = _FakeSession(post_exc=aiohttp.ClientError("reset"))
    transport = AiohttpTransport(session_factory=_SessionFactory([session]))
    with pytest.raises(InferenceTransportError):
        await _post(transport)


async def test_aiohttp_transport_aclose_without_session_is_noop():
    # A fresh transport (no request yet, lock not created) closes cleanly.
    transport = AiohttpTransport(session_factory=_SessionFactory([]))
    await transport.aclose()


async def test_aiohttp_transport_aclose_skips_already_closed_session():
    # Session reports closed (e.g. closed underneath us): aclose must not double-close.
    s = _FakeSession([_FakeResp(200, {})])
    transport = AiohttpTransport(session_factory=_SessionFactory([s]))
    await _post(transport)
    s.closed = True
    await transport.aclose()  # non-None but already closed → no second close, no error


async def test_aiohttp_transport_aclose_is_idempotent_and_recreates():
    s1 = _FakeSession([_FakeResp(200, {"ok": 1})])
    s2 = _FakeSession([_FakeResp(200, {"ok": 2})])
    factory = _SessionFactory([s1, s2])
    transport = AiohttpTransport(session_factory=factory)

    await _post(transport)
    await transport.aclose()
    assert s1.closed is True
    await transport.aclose()  # second close is a no-op, not an error

    await _post(transport)  # a closed session is replaced
    assert factory.created == 2
    assert s2.post_calls == 1


def test_require_aiohttp_passes_when_available():
    """Should not raise when aiohttp is installed."""
    _require_aiohttp()


def test_require_aiohttp_raises_when_absent(monkeypatch):
    """The actionable error fires when aiohttp is not installed."""
    monkeypatch.setattr(inference_transport_mod, "aiohttp", None)
    with pytest.raises(RuntimeError, match="meshsa\\[inference\\]"):
        _require_aiohttp()
