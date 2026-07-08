"""Inference-layer tests.

The HTTP boundary is exercised through an injected ``FakeHttpTransport`` (the
``make_transport`` fixture) — pure, no ``aiohttp`` and no sockets — so these tests
are independent of any ``aiohttp`` version. The retry/backoff/parse logic under
test lives entirely in :class:`NemotronClient`; the real socket transport
(:class:`AiohttpTransport`) is the only ``# pragma: no cover`` glue.
"""

import asyncio

import pytest

import meshsa.inference as inference_mod
from meshsa import (
    AiohttpTransport,
    Envelope,
    HttpResponse,
    HttpTransport,
    InferenceError,
    InferenceHttpError,
    InferenceService,
    InferenceTransportError,
    MessageKind,
    NemotronClient,
    NemotronConfig,
    SystemClock,
    UuidFactory,
)
from meshsa.inference import _DEFAULT_INSIGHT_PREFIX, _is_ai_insight, _require_aiohttp


def _ok(content: str) -> HttpResponse:
    """A 200 response shaped like the NIM chat-completions payload."""
    return HttpResponse(status=200, payload={"choices": [{"message": {"content": content}}]})


async def _noop_sleep(_delay: float) -> None:
    """A sleep that records nothing and never yields wall-clock time."""


@pytest.fixture
def env():
    return Envelope(
        schema_version=1,
        msg_id="msg-1",
        ts=1.0,
        source_uid="node-a",
        kind=MessageKind.PLI,
        payload={"position": {"lat": 1.0, "lon": 2.0}},
    )


@pytest.fixture
def mock_router():
    class MockRouter:
        def __init__(self):
            self.handlers = []
            self.published = []

        def subscribe(self, handler):
            self.handlers.append(handler)

        async def publish(self, envelope):
            self.published.append(envelope)

    return MockRouter()


# ── NemotronClient ──────────────────────────────────────────────────────


async def test_nemotron_client_success(make_transport, env):
    cfg = NemotronConfig(enabled=True, api_key="nvapi-test")
    transport = make_transport([_ok("Test summary")])
    client = NemotronClient(cfg, transport=transport)

    result = await client.analyze(env)
    assert result.summary == "Test summary"
    # Request shape: signed bearer header + chat-completions endpoint.
    call = transport.calls[0]
    assert call["url"].endswith("/chat/completions")
    assert call["headers"]["Authorization"] == "Bearer nvapi-test"
    assert call["timeout_s"] == cfg.timeout_s


async def test_nemotron_client_satisfies_protocol(make_transport):
    # The fake is a structural HttpTransport (runtime-checkable Protocol).
    assert isinstance(make_transport([]), HttpTransport)


async def test_nemotron_client_disabled(make_transport, env):
    cfg = NemotronConfig(enabled=False)
    transport = make_transport([])
    client = NemotronClient(cfg, transport=transport)
    result = await client.analyze(env)
    assert result.summary == ""
    assert transport.calls == []  # short-circuits before any HTTP call


async def test_nemotron_client_retry_on_429(make_transport, env):
    cfg = NemotronConfig(enabled=True, api_key="nvapi-test", max_retries=1)
    transport = make_transport([HttpResponse(status=429, payload={}), _ok("Recovered")])
    client = NemotronClient(cfg, sleep=_noop_sleep, transport=transport)

    result = await client.analyze(env)
    assert result.summary == "Recovered"
    assert len(transport.calls) == 2


async def test_nemotron_client_persistent_429_raises(make_transport, env):
    cfg = NemotronConfig(enabled=True, api_key="nvapi-test", max_retries=1)
    transport = make_transport([HttpResponse(status=429, payload={}) for _ in range(2)])
    client = NemotronClient(cfg, sleep=_noop_sleep, transport=transport)

    with pytest.raises(InferenceHttpError) as exc:
        await client.analyze(env)
    assert exc.value.status == 429
    assert len(transport.calls) == 2


async def test_nemotron_client_timeout_propagates(make_transport, env):
    cfg = NemotronConfig(enabled=True, api_key="nvapi-test", timeout_s=0.1, max_retries=0)
    transport = make_transport([InferenceTransportError("timed out")])
    client = NemotronClient(cfg, transport=transport)

    with pytest.raises(InferenceTransportError):
        await client.analyze(env)


# ── InferenceService ────────────────────────────────────────────────────


async def test_inference_service_publishes_chat(make_transport, mock_router, env):
    cfg = NemotronConfig(enabled=True, api_key="nvapi-test")
    svc = InferenceService(
        config=cfg,
        router=mock_router,
        clock=SystemClock(),
        id_factory=UuidFactory(),
        source_uid="node-base",
        transport=make_transport([_ok("Insightful observation")]),
    )

    svc.start()
    assert len(mock_router.handlers) == 1

    # Simulate inbound message
    await mock_router.handlers[0](env)

    # Bounded retry — wait until the bg task publishes rather than fixed sleep
    for _ in range(200):
        if mock_router.published:
            break
        await asyncio.sleep(0)
    await svc.stop()

    assert len(mock_router.published) == 1
    reply = mock_router.published[0]
    assert reply.kind == MessageKind.CHAT
    assert reply.source_uid == "node-base"
    assert reply.payload["to"] == "node-a"
    assert "Insightful observation" in reply.payload["text"]


async def test_inference_service_ignores_own_messages(mock_router):
    cfg = NemotronConfig(enabled=True, api_key="nvapi-test")
    svc = InferenceService(
        config=cfg,
        router=mock_router,
        clock=SystemClock(),
        id_factory=UuidFactory(),
        source_uid="node-base",
    )
    svc.start()

    env = Envelope(
        schema_version=1,
        msg_id="self-msg",
        ts=1.0,
        source_uid="node-base",  # Same as service source_uid
        kind=MessageKind.CHAT,
        payload={"text": "hello"},
    )

    await mock_router.handlers[0](env)
    assert len(svc._bg_tasks) == 0  # Task was not spawned


# ── AI insight feedback loop prevention ─────────────────────────────────


async def test_inference_service_ignores_ai_insights(mock_router):
    """Messages prefixed with [AI Insight] must be silently dropped."""
    cfg = NemotronConfig(enabled=True, api_key="nvapi-test")
    svc = InferenceService(
        config=cfg,
        router=mock_router,
        clock=SystemClock(),
        id_factory=UuidFactory(),
        source_uid="node-base",
    )
    svc.start()

    insight_env = Envelope(
        schema_version=1,
        msg_id="ai-loop-msg",
        ts=2.0,
        source_uid="node-other",
        kind=MessageKind.CHAT,
        payload={"text": f"{_DEFAULT_INSIGHT_PREFIX} Summary of something"},
    )

    await mock_router.handlers[0](insight_env)
    assert len(svc._bg_tasks) == 0


def test_is_ai_insight_true():
    env = Envelope(
        schema_version=1,
        msg_id="x",
        ts=1.0,
        source_uid="a",
        kind=MessageKind.CHAT,
        payload={"text": f"{_DEFAULT_INSIGHT_PREFIX} some text"},
    )
    assert _is_ai_insight(env) is True


def test_is_ai_insight_false_pli():
    env = Envelope(
        schema_version=1,
        msg_id="x",
        ts=1.0,
        source_uid="a",
        kind=MessageKind.PLI,
        payload={"position": {"lat": 0, "lon": 0}},
    )
    assert _is_ai_insight(env) is False


def test_is_ai_insight_false_normal_chat():
    env = Envelope(
        schema_version=1,
        msg_id="x",
        ts=1.0,
        source_uid="a",
        kind=MessageKind.CHAT,
        payload={"text": "regular message"},
    )
    assert _is_ai_insight(env) is False


# ── _running lifecycle guard ────────────────────────────────────────────


async def test_inference_service_ignores_after_stop(mock_router, env):
    """After stop() is called, handle_message must not spawn tasks."""
    cfg = NemotronConfig(enabled=True, api_key="nvapi-test")
    svc = InferenceService(
        config=cfg,
        router=mock_router,
        clock=SystemClock(),
        id_factory=UuidFactory(),
        source_uid="node-base",
    )
    svc.start()
    await svc.stop()

    # Router still has the handler reference but service is stopped
    await mock_router.handlers[0](env)
    assert len(svc._bg_tasks) == 0


# ── double-start guard ──────────────────────────────────────────────────


async def test_inference_service_double_start_no_duplicate_subscribe(mock_router):
    cfg = NemotronConfig(enabled=True, api_key="nvapi-test")
    svc = InferenceService(
        config=cfg,
        router=mock_router,
        clock=SystemClock(),
        id_factory=UuidFactory(),
        source_uid="node-base",
    )
    svc.start()
    svc.start()  # second start must be idempotent
    assert len(mock_router.handlers) == 1


# ── missing API key logs warning and does not subscribe ─────────────────


async def test_inference_service_missing_api_key_does_not_start(mock_router):
    cfg = NemotronConfig(enabled=True, api_key="")
    svc = InferenceService(
        config=cfg,
        router=mock_router,
        clock=SystemClock(),
        id_factory=UuidFactory(),
        source_uid="node-base",
    )
    svc.start()
    assert len(mock_router.handlers) == 0
    assert svc._running is False


# ── _require_aiohttp guard ──────────────────────────────────────────────


def test_require_aiohttp_passes_when_available():
    """Should not raise when aiohttp is installed."""
    _require_aiohttp()


# ── Transport-error and lifecycle coverage ──────────────────────────────


async def test_nemotron_client_transport_error_propagates(make_transport, env):
    """A transport error on the final attempt must propagate after logging."""
    cfg = NemotronConfig(enabled=True, api_key="nvapi-test", max_retries=0)
    transport = make_transport([InferenceTransportError("connection reset")])
    client = NemotronClient(cfg, transport=transport)

    with pytest.raises(InferenceTransportError):
        await client.analyze(env)


async def test_close_delegates_to_transport(make_transport):
    cfg = NemotronConfig(enabled=True, api_key="nvapi-test")
    transport = make_transport([])
    client = NemotronClient(cfg, transport=transport)
    await client.close()
    assert transport.closed is True


async def test_analyze_and_publish_empty_summary_noop(make_transport, mock_router, env):
    """When the API returns an empty summary, no message should be published."""
    cfg = NemotronConfig(enabled=True, api_key="nvapi-test")
    svc = InferenceService(
        config=cfg,
        router=mock_router,
        clock=SystemClock(),
        id_factory=UuidFactory(),
        source_uid="node-base",
        transport=make_transport([_ok("")]),
    )

    svc.start()
    await mock_router.handlers[0](env)

    for _ in range(200):
        if not svc._bg_tasks:
            break
        await asyncio.sleep(0)
    await svc.stop()

    assert len(mock_router.published) == 0


async def test_analyze_and_publish_exception_logged(make_transport, mock_router, env):
    """When the API call fails, the exception should be caught and logged."""
    cfg = NemotronConfig(enabled=True, api_key="nvapi-test", max_retries=0)
    svc = InferenceService(
        config=cfg,
        router=mock_router,
        clock=SystemClock(),
        id_factory=UuidFactory(),
        source_uid="node-base",
        transport=make_transport([InferenceTransportError("boom")]),
    )

    svc.start()
    await mock_router.handlers[0](env)

    for _ in range(200):
        if not svc._bg_tasks:
            break
        await asyncio.sleep(0)
    await svc.stop()

    # Exception was caught — no message published, no unhandled error
    assert len(mock_router.published) == 0


async def test_nemotron_client_no_api_key_returns_empty(make_transport, env):
    """When api_key is empty but enabled is True, analyze returns empty result."""
    cfg = NemotronConfig(enabled=True, api_key="")
    client = NemotronClient(cfg, transport=make_transport([]))
    result = await client.analyze(env)
    assert result.summary == ""
    assert result.raw_response == ""


# ── Server error and malformed response tests ───────────────────────────


async def test_nemotron_client_500_error_raises(make_transport, env):
    """5xx server errors should propagate as InferenceHttpError carrying the status."""
    cfg = NemotronConfig(enabled=True, api_key="nvapi-test", max_retries=0)
    transport = make_transport([HttpResponse(status=500, payload={})])
    client = NemotronClient(cfg, transport=transport)

    with pytest.raises(InferenceHttpError) as exc:
        await client.analyze(env)
    assert exc.value.status == 500


async def test_nemotron_client_500_retried_then_raised(make_transport, env):
    """A retryable 5xx is retried up to the budget, then fails closed."""
    cfg = NemotronConfig(enabled=True, api_key="nvapi-test", max_retries=1)
    transport = make_transport([HttpResponse(status=500, payload={}) for _ in range(2)])
    client = NemotronClient(cfg, sleep=_noop_sleep, transport=transport)

    with pytest.raises(InferenceHttpError) as exc:
        await client.analyze(env)
    assert exc.value.status == 500
    assert len(transport.calls) == 2  # one initial + one retry


async def test_nemotron_client_malformed_json_maps_to_inference_error(make_transport, env):
    """A 200 body missing 'choices' fails as InferenceError, not a raw KeyError (no retry)."""
    cfg = NemotronConfig(enabled=True, api_key="nvapi-test", max_retries=0)
    transport = make_transport([HttpResponse(status=200, payload={"error": "unexpected"})])
    client = NemotronClient(cfg, transport=transport)

    with pytest.raises(InferenceError):
        await client.analyze(env)
    assert len(transport.calls) == 1  # a malformed body is not transient — no retry


async def test_nemotron_client_empty_choices_maps_to_inference_error(make_transport, env):
    """An empty 'choices' array fails as InferenceError, not a raw IndexError."""
    cfg = NemotronConfig(enabled=True, api_key="nvapi-test", max_retries=0)
    transport = make_transport([HttpResponse(status=200, payload={"choices": []})])
    client = NemotronClient(cfg, transport=transport)

    with pytest.raises(InferenceError):
        await client.analyze(env)


async def test_nemotron_client_4xx_fails_fast(make_transport, env):
    """A non-429 4xx (e.g. 401 bad key) fails immediately — it must not burn the retry budget."""
    cfg = NemotronConfig(enabled=True, api_key="bad-key", max_retries=3)
    transport = make_transport([HttpResponse(status=401, payload={}) for _ in range(4)])
    client = NemotronClient(cfg, sleep=_noop_sleep, transport=transport)

    with pytest.raises(InferenceHttpError) as exc:
        await client.analyze(env)
    assert exc.value.status == 401
    assert len(transport.calls) == 1  # fail fast: exactly one attempt


async def test_nemotron_client_backoff_is_capped(make_transport, env):
    """Backoff delay is clamped to backoff_max_s rather than growing unbounded."""
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    cfg = NemotronConfig(
        enabled=True, api_key="nvapi-test", max_retries=3, backoff_base=10.0, backoff_max_s=5.0
    )
    transport = make_transport(
        [HttpResponse(status=503, payload={}) for _ in range(3)] + [_ok("ok")]
    )
    client = NemotronClient(cfg, sleep=fake_sleep, transport=transport)

    result = await client.analyze(env)
    assert result.summary == "ok"
    # 10**0=1.0, then 10**1 and 10**2 are clamped to 5.0
    assert sleeps == [1.0, 5.0, 5.0]


# ── Injectable sleep and configurable backoff ─────────────────────────


async def test_nemotron_client_uses_injectable_sleep_and_backoff_base(make_transport, env):
    """Custom sleep and backoff_base should be used during 429 retries."""
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    cfg = NemotronConfig(enabled=True, api_key="nvapi-test", max_retries=2, backoff_base=3.0)
    transport = make_transport(
        [HttpResponse(status=429, payload={}), HttpResponse(status=429, payload={}), _ok("Finally")]
    )
    client = NemotronClient(cfg, sleep=fake_sleep, transport=transport)

    result = await client.analyze(env)
    assert result.summary == "Finally"
    # backoff_base=3.0: sleep(3**0)=1.0, sleep(3**1)=3.0
    assert sleeps == [1.0, 3.0]


async def test_nemotron_client_injectable_sleep_on_transient_error(make_transport, env):
    """Injectable sleep should be used during transient error retries too."""
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    cfg = NemotronConfig(enabled=True, api_key="nvapi-test", max_retries=1, backoff_base=2.0)
    transport = make_transport([InferenceTransportError("transient"), _ok("OK")])
    client = NemotronClient(cfg, sleep=fake_sleep, transport=transport)

    result = await client.analyze(env)
    assert result.summary == "OK"
    # backoff_base=2.0: sleep(2**0)=1.0
    assert sleeps == [1.0]


async def test_analyze_and_publish_propagates_cancellation(mock_router, env):
    """Cooperative cancellation must propagate, not be swallowed as a task failure."""

    class _CancellingTransport:
        async def post_json(self, url, *, headers, json_body, timeout_s):
            raise asyncio.CancelledError

        async def aclose(self) -> None:
            pass

    cfg = NemotronConfig(enabled=True, api_key="nvapi-test", max_retries=0)
    svc = InferenceService(
        config=cfg,
        router=mock_router,
        clock=SystemClock(),
        id_factory=UuidFactory(),
        source_uid="node-base",
        transport=_CancellingTransport(),
    )

    with pytest.raises(asyncio.CancelledError):
        await svc._analyze_and_publish(env)
    assert mock_router.published == []


# ── AiohttpTransport: session-reuse + error mapping (no real sockets) ────
#
# A fake aiohttp-style session covers the transport logic that would otherwise
# only run against a live socket. Only real ``aiohttp.ClientSession`` creation
# stays ``# pragma: no cover``.


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


def test_require_aiohttp_raises_when_absent(monkeypatch):
    """The actionable error fires when aiohttp is not installed."""
    monkeypatch.setattr(inference_mod, "aiohttp", None)
    with pytest.raises(RuntimeError, match="meshsa\\[inference\\]"):
        _require_aiohttp()


# ── Track-B: structured (JSON) response parsing ─────────────────────────


async def test_client_guided_json_sends_nvext_and_extracts_summary(make_transport, env):
    """A guided_json_schema is sent as nvext.guided_json and a JSON reply is unwrapped."""
    cfg = NemotronConfig(enabled=True, api_key="k", guided_json_schema='{"type": "object"}')
    transport = make_transport([_ok('{"summary": "structured reply"}')])
    client = NemotronClient(cfg, transport=transport)

    result = await client.analyze(env)
    assert result.summary == "structured reply"
    body = transport.calls[0]["json_body"]
    assert body["nvext"] == {"guided_json": {"type": "object"}}
    assert "response_format" not in body  # schema wins; the portable toggle is not sent


async def test_client_response_format_json_sends_toggle_and_extracts(make_transport, env):
    """response_format='json' (no schema) sends the portable OpenAI JSON toggle."""
    cfg = NemotronConfig(enabled=True, api_key="k", response_format="json")
    transport = make_transport([_ok('{"summary": "hi"}')])
    client = NemotronClient(cfg, transport=transport)

    result = await client.analyze(env)
    assert result.summary == "hi"
    body = transport.calls[0]["json_body"]
    assert body["response_format"] == {"type": "json_object"}
    assert "nvext" not in body


async def test_client_json_mode_falls_back_to_raw_on_non_json(make_transport, env):
    """A structured request whose reply is not JSON keeps the raw text (never lost)."""
    cfg = NemotronConfig(enabled=True, api_key="k", response_format="json")
    client = NemotronClient(cfg, transport=make_transport([_ok("just prose")]))
    result = await client.analyze(env)
    assert result.summary == "just prose"


async def test_client_json_mode_dict_without_summary_keeps_raw(make_transport, env):
    """A JSON object lacking a string 'summary' field falls back to the raw content."""
    cfg = NemotronConfig(enabled=True, api_key="k", response_format="json")
    client = NemotronClient(cfg, transport=make_transport([_ok('{"other": 1}')]))
    result = await client.analyze(env)
    assert result.summary == '{"other": 1}'


async def test_client_text_mode_sends_no_structured_directive(make_transport, env):
    """The default text mode sends neither nvext nor response_format."""
    cfg = NemotronConfig(enabled=True, api_key="k")
    transport = make_transport([_ok("plain")])
    client = NemotronClient(cfg, transport=transport)
    await client.analyze(env)
    body = transport.calls[0]["json_body"]
    assert "nvext" not in body and "response_format" not in body


async def test_client_guided_json_summary_field_is_configurable(make_transport, env):
    """The unwrap key follows guided_json_summary_field, not a hardcoded 'summary'."""
    cfg = NemotronConfig(
        enabled=True,
        api_key="k",
        guided_json_schema='{"type": "object"}',
        guided_json_summary_field="report",
    )
    transport = make_transport([_ok('{"report": "custom-key reply", "summary": "ignored"}')])
    client = NemotronClient(cfg, transport=transport)
    result = await client.analyze(env)
    assert result.summary == "custom-key reply"


async def test_client_json_mode_missing_configured_field_falls_back(make_transport, env):
    """When the configured field is absent, fall back to raw text (never lose the reply)."""
    cfg = NemotronConfig(
        enabled=True, api_key="k", response_format="json", guided_json_summary_field="report"
    )
    client = NemotronClient(cfg, transport=make_transport([_ok('{"summary": "wrong key"}')]))
    result = await client.analyze(env)
    assert result.summary == '{"summary": "wrong key"}'


# ── Track-B: rate limiting (concurrency + min-interval) ─────────────────


class _FixedClock:
    """A clock frozen at one instant, so elapsed-since-last is always zero."""

    def now(self) -> float:
        return 100.0


async def _await_published(mock_router, n: int) -> None:
    for _ in range(1000):
        if len(mock_router.published) >= n:
            return
        await asyncio.sleep(0)
    raise AssertionError(f"expected >= {n} published, got {len(mock_router.published)}")


async def _await_idle(svc) -> None:
    for _ in range(1000):
        if not svc._bg_tasks:
            return
        await asyncio.sleep(0)
    raise AssertionError(f"service never became idle: {len(svc._bg_tasks)} task(s) still running")


def _service(cfg, mock_router, transport, *, clock=None, sleep=None):
    kwargs = {}
    if sleep is not None:
        kwargs["sleep"] = sleep
    return InferenceService(
        config=cfg,
        router=mock_router,
        clock=clock or SystemClock(),
        id_factory=UuidFactory(),
        source_uid="node-base",
        transport=transport,
        **kwargs,
    )


async def test_service_min_interval_spaces_requests(make_transport, mock_router, env):
    """With a frozen clock, the second request waits min_interval_s; the first does not."""
    sleeps: list[float] = []

    async def rec_sleep(delay: float) -> None:
        sleeps.append(delay)

    cfg = NemotronConfig(enabled=True, api_key="k", min_interval_s=0.5)
    svc = _service(
        cfg, mock_router, make_transport([_ok("a"), _ok("b")]), clock=_FixedClock(), sleep=rec_sleep
    )
    svc.start()
    await mock_router.handlers[0](env)
    await mock_router.handlers[0](env)
    await _await_published(mock_router, 2)
    await svc.stop()

    assert len(mock_router.published) == 2
    assert sleeps == [pytest.approx(0.5)]  # exactly one spacing wait, for the 2nd request


async def test_service_min_interval_no_wait_when_elapsed_exceeds(
    make_transport, mock_router, env, clock
):
    """When more than min_interval_s has elapsed, no spacing wait occurs (wait<=0 branch)."""
    sleeps: list[float] = []

    async def rec_sleep(delay: float) -> None:
        sleeps.append(delay)

    # The conftest FakeClock (via the `clock` fixture) advances 1.0s per now() call — always
    # > 0.5s of spacing.
    cfg = NemotronConfig(enabled=True, api_key="k", min_interval_s=0.5)
    svc = _service(
        cfg, mock_router, make_transport([_ok("a"), _ok("b")]), clock=clock, sleep=rec_sleep
    )
    svc.start()
    await mock_router.handlers[0](env)
    await _await_idle(svc)
    await mock_router.handlers[0](env)
    await _await_published(mock_router, 2)
    await svc.stop()

    assert sleeps == []  # clock advanced past the interval — never waited


def test_service_bounded_semaphore_created_when_configured(mock_router, make_transport):
    cfg = NemotronConfig(enabled=True, api_key="k", max_concurrent_requests=2)
    svc = _service(cfg, mock_router, make_transport([]))
    assert isinstance(svc._semaphore, asyncio.BoundedSemaphore)


def test_service_no_semaphore_by_default(mock_router, make_transport):
    cfg = NemotronConfig(enabled=True, api_key="k")
    svc = _service(cfg, mock_router, make_transport([]))
    assert svc._semaphore is None


async def test_service_publishes_under_concurrency_limit(make_transport, mock_router, env):
    """Two messages both publish while gated by a max_concurrent_requests=1 semaphore."""
    cfg = NemotronConfig(enabled=True, api_key="k", max_concurrent_requests=1)
    svc = _service(cfg, mock_router, make_transport([_ok("a"), _ok("b")]))
    svc.start()
    await mock_router.handlers[0](env)
    await mock_router.handlers[0](env)
    await _await_published(mock_router, 2)
    await svc.stop()
    assert len(mock_router.published) == 2


# ── Track-B: offline queue (enqueue-on-failure, replay-on-recovery) ─────


async def test_service_offline_queue_replays_on_recovery(make_transport, mock_router, env):
    """A failed analysis is queued, then replayed and published on the next success."""
    cfg = NemotronConfig(enabled=True, api_key="k", max_retries=0, offline_queue_max=4)
    # msg1 fails; msg2 succeeds (publishes s2) then drains msg1 (publishes s1-replay).
    transport = make_transport([InferenceTransportError("down"), _ok("s2"), _ok("s1-replay")])
    svc = _service(cfg, mock_router, transport)
    svc.start()

    await mock_router.handlers[0](env)  # message 1 -> fails -> queued
    await _await_idle(svc)
    assert svc._offline is not None and len(svc._offline) == 1

    await mock_router.handlers[0](env)  # message 2 -> success -> publish + drain replay
    await _await_published(mock_router, 2)
    await svc.stop()

    assert len(mock_router.published) == 2
    assert not svc._offline  # queue drained


async def test_service_offline_queue_drops_oldest_when_full(make_transport, mock_router, env):
    """Overflow drops the oldest and increments the drop counter (drop-and-count)."""
    cfg = NemotronConfig(enabled=True, api_key="k", max_retries=0, offline_queue_max=1)
    transport = make_transport([InferenceTransportError("x")], repeat_last=True)
    svc = _service(cfg, mock_router, transport)
    svc.start()

    await mock_router.handlers[0](env)
    await _await_idle(svc)
    await mock_router.handlers[0](env)
    await _await_idle(svc)
    await svc.stop()

    assert svc._offline is not None and len(svc._offline) == 1
    assert svc._offline_dropped == 1


async def test_service_offline_replay_requeues_on_repeat_failure(make_transport, mock_router, env):
    """If a replay fails again, the envelope is re-queued and draining stops."""
    cfg = NemotronConfig(enabled=True, api_key="k", max_retries=0, offline_queue_max=4)
    # msg1 fails -> queued; msg2 ok -> publish; drain replays msg1 -> fails -> re-queued.
    transport = make_transport(
        [InferenceTransportError("a"), _ok("s2"), InferenceTransportError("b")]
    )
    svc = _service(cfg, mock_router, transport)
    svc.start()

    await mock_router.handlers[0](env)
    await _await_idle(svc)
    await mock_router.handlers[0](env)
    await _await_published(mock_router, 1)
    await svc.stop()

    assert len(mock_router.published) == 1  # only s2
    assert svc._offline is not None and len(svc._offline) == 1  # msg1 back in the queue


async def test_service_offline_replay_skips_empty_summary(make_transport, mock_router, env):
    """A replay that yields an empty summary is not published (drain's summary guard)."""
    cfg = NemotronConfig(enabled=True, api_key="k", max_retries=0, offline_queue_max=4)
    # msg1 fails -> queued; msg2 ok -> publish; drain replays msg1 -> empty content -> no publish.
    transport = make_transport([InferenceTransportError("a"), _ok("s2"), _ok("")])
    svc = _service(cfg, mock_router, transport)
    svc.start()

    await mock_router.handlers[0](env)
    await _await_idle(svc)
    await mock_router.handlers[0](env)
    await _await_published(mock_router, 1)
    await _await_idle(svc)
    await svc.stop()

    assert len(mock_router.published) == 1  # only s2; the empty replay is dropped
    assert not svc._offline


def _pli(msg_id: str, source_uid: str) -> Envelope:
    return Envelope(
        schema_version=1,
        msg_id=msg_id,
        ts=1.0,
        source_uid=source_uid,
        kind=MessageKind.PLI,
        payload={"position": {"lat": 1.0, "lon": 2.0}},
    )


async def test_service_offline_replay_failure_preserves_fifo_order(make_transport, mock_router):
    """A failed replay returns to the FRONT of the queue, ahead of newer entries (FIFO)."""
    cfg = NemotronConfig(enabled=True, api_key="k", max_retries=0, offline_queue_max=4)
    a, b, c = _pli("a", "u1"), _pli("b", "u2"), _pli("c", "u3")
    # a fails -> [a]; b fails -> [a, b]; c ok -> publish, drain pops a -> fails -> back to front.
    transport = make_transport(
        [
            InferenceTransportError("a"),
            InferenceTransportError("b"),
            _ok("c-ok"),
            InferenceTransportError("a2"),
        ]
    )
    svc = _service(cfg, mock_router, transport)
    svc.start()

    await mock_router.handlers[0](a)
    await _await_idle(svc)
    await mock_router.handlers[0](b)
    await _await_idle(svc)
    await mock_router.handlers[0](c)
    await _await_published(mock_router, 1)
    await _await_idle(svc)
    await svc.stop()

    assert len(mock_router.published) == 1  # only c
    assert svc._offline is not None
    # 'a' stayed at the front (appendleft), 'b' still behind it — arrival order preserved.
    assert [e.msg_id for e in svc._offline] == ["a", "b"]


# ── Track-B hardening: offline error classification + gated drain ───────


async def test_service_permanent_http_error_not_queued(make_transport, mock_router, env):
    """A permanent 4xx (401 bad key) must NOT be queued for offline replay."""
    cfg = NemotronConfig(enabled=True, api_key="bad", max_retries=0, offline_queue_max=4)
    svc = _service(cfg, mock_router, make_transport([HttpResponse(status=401, payload={})]))
    svc.start()
    await mock_router.handlers[0](env)
    await _await_idle(svc)
    await svc.stop()
    assert mock_router.published == []
    assert svc._offline is not None and len(svc._offline) == 0  # not queued — fails fast


async def test_service_malformed_payload_not_queued(make_transport, mock_router, env):
    """A malformed 200 body (base InferenceError) must NOT be queued (never replays clean)."""
    cfg = NemotronConfig(enabled=True, api_key="k", max_retries=0, offline_queue_max=4)
    svc = _service(cfg, mock_router, make_transport([HttpResponse(status=200, payload={"x": 1})]))
    svc.start()
    await mock_router.handlers[0](env)
    await _await_idle(svc)
    await svc.stop()
    assert mock_router.published == []
    assert svc._offline is not None and len(svc._offline) == 0


async def test_service_5xx_exhausted_is_queued(make_transport, mock_router, env):
    """A 5xx that survives retries IS transient → queued for offline replay."""
    cfg = NemotronConfig(enabled=True, api_key="k", max_retries=0, offline_queue_max=4)
    svc = _service(cfg, mock_router, make_transport([HttpResponse(status=503, payload={})]))
    svc.start()
    await mock_router.handlers[0](env)
    await _await_idle(svc)
    await svc.stop()
    assert svc._offline is not None and len(svc._offline) == 1


async def test_service_drain_honors_min_interval(make_transport, mock_router, env):
    """Offline replay goes through the same _space() gate as live requests (no burst)."""
    sleeps: list[float] = []

    async def rec_sleep(delay: float) -> None:
        sleeps.append(delay)

    cfg = NemotronConfig(
        enabled=True, api_key="k", max_retries=0, offline_queue_max=4, min_interval_s=0.5
    )
    # msg1 fails (transient) -> queued; msg2 ok -> publish + drain replays msg1 ok.
    transport = make_transport([InferenceTransportError("down"), _ok("s2"), _ok("s1")])
    svc = _service(cfg, mock_router, transport, clock=_FixedClock(), sleep=rec_sleep)
    svc.start()
    await mock_router.handlers[0](env)
    await _await_idle(svc)
    await mock_router.handlers[0](env)
    await _await_published(mock_router, 2)
    await svc.stop()
    # 3 gated calls total (fail, live-ok, replay-ok); the 2nd and 3rd each wait one interval.
    assert sleeps == [pytest.approx(0.5), pytest.approx(0.5)]


async def test_service_drain_drops_permanent_and_continues(make_transport, mock_router):
    """A replay failing permanently is dropped (counted) and draining continues to the next."""
    a, b, c = _pli("a", "u1"), _pli("b", "u2"), _pli("c", "u3")
    cfg = NemotronConfig(enabled=True, api_key="k", max_retries=0, offline_queue_max=4)
    # a,b fail (transient) -> [a, b]; c ok -> publish; drain: a -> 401 permanent (drop+continue),
    # b -> ok (publish).
    transport = make_transport(
        [
            InferenceTransportError("a"),
            InferenceTransportError("b"),
            _ok("c-ok"),
            HttpResponse(status=401, payload={}),
            _ok("b-replay"),
        ]
    )
    svc = _service(cfg, mock_router, transport)
    svc.start()
    await mock_router.handlers[0](a)
    await _await_idle(svc)
    await mock_router.handlers[0](b)
    await _await_idle(svc)
    await mock_router.handlers[0](c)
    await _await_published(mock_router, 2)
    await _await_idle(svc)
    await svc.stop()

    assert len(mock_router.published) == 2  # c-ok + b-replay; 'a' was dropped as permanent
    assert svc._offline is not None and len(svc._offline) == 0
    assert svc._offline_dropped == 1


async def test_service_non_inference_exception_logged_not_queued(make_transport, mock_router, env):
    """A non-InferenceError (e.g. an unexpected bug) is caught + logged, never queued or raised."""
    cfg = NemotronConfig(enabled=True, api_key="k", max_retries=0, offline_queue_max=4)
    # A plain RuntimeError from the transport is not an InferenceError — it bypasses the retry
    # loop and the offline classifier, hitting the task-level safety net.
    svc = _service(cfg, mock_router, make_transport([RuntimeError("unexpected bug")]))
    svc.start()
    await mock_router.handlers[0](env)
    await _await_idle(svc)
    await svc.stop()
    assert mock_router.published == []
    assert svc._offline is not None and len(svc._offline) == 0  # generic errors aren't queued


# ── Backpressure: bound handle_message task intake (max_pending_tasks) ──────


def _chat_envelope(text: str, *, source_uid: str) -> Envelope:
    return Envelope(
        schema_version=1,
        msg_id="chat-1",
        ts=1.0,
        source_uid=source_uid,
        kind=MessageKind.CHAT,
        payload={"text": text},
    )


async def test_handle_message_sheds_when_pending_tasks_at_cap(make_transport, mock_router):
    # With the cap reached, a new inbound envelope is dropped-and-counted, no task spawned.
    cfg = NemotronConfig(enabled=True, api_key="k", max_pending_tasks=1)
    svc = _service(cfg, mock_router, make_transport([]))
    svc._running = True
    # Simulate one in-flight task already occupying the only slot.
    slow = asyncio.get_event_loop().create_future()
    svc._bg_tasks.add(asyncio.ensure_future(slow))
    await svc.handle_message(_chat_envelope("hello", source_uid="other"))
    assert svc._intake_dropped == 1
    assert len(svc._bg_tasks) == 1  # no new task added
    slow.set_result(None)


async def test_handle_message_accepts_below_cap_then_sheds_at_cap(make_transport, mock_router):
    # cap=3 (not the degenerate cap=1 case): below cap must accept and spawn a task;
    # only once occupancy reaches the cap does intake shed.
    cfg = NemotronConfig(enabled=True, api_key="k", max_pending_tasks=3)
    svc = _service(cfg, mock_router, make_transport([]))
    svc._running = True

    # Occupy 2 of 3 slots with fake in-flight tasks (mirrors the cap=1 shed test's technique).
    slow1 = asyncio.get_event_loop().create_future()
    slow2 = asyncio.get_event_loop().create_future()
    svc._bg_tasks.add(asyncio.ensure_future(slow1))
    svc._bg_tasks.add(asyncio.ensure_future(slow2))

    # len(_bg_tasks)==2 < cap==3: the envelope must be accepted (a new task scheduled),
    # not shed — the accept-path signal, mirrored by the dropped counter staying put.
    await svc.handle_message(_chat_envelope("hello", source_uid="other"))
    assert svc._intake_dropped == 0
    assert len(svc._bg_tasks) == 3  # 2 fakes + 1 newly-spawned real task

    # Occupy the 3rd slot with a fake too, so occupancy is deterministically pinned at the
    # cap (3) rather than depending on the real task above ever completing.
    slow3 = asyncio.get_event_loop().create_future()
    svc._bg_tasks.add(asyncio.ensure_future(slow3))
    assert len(svc._bg_tasks) == 4  # 3 fakes + 1 real, all still in-flight

    # len(_bg_tasks)==4 >= cap==3: the next envelope must now be shed.
    await svc.handle_message(_chat_envelope("world", source_uid="other"))
    assert svc._intake_dropped == 1
    assert len(svc._bg_tasks) == 4  # no new task added

    slow1.set_result(None)
    slow2.set_result(None)
    slow3.set_result(None)


async def test_handle_message_unbounded_when_cap_zero(make_transport, mock_router):
    cfg = NemotronConfig(enabled=True, api_key="k", max_pending_tasks=0)
    svc = _service(cfg, mock_router, make_transport([_ok("hi-reply")]))
    svc._running = True
    await svc.handle_message(_chat_envelope("hi", source_uid="other"))
    assert svc._intake_dropped == 0
    await _await_published(mock_router, 1)
    await svc.stop()


# ── InferenceService.as_dict(): point-in-time counters accessor ─────────────


def test_as_dict_reports_counters(mock_router, make_transport):
    cfg = NemotronConfig(enabled=True, api_key="k", offline_queue_max=4, max_pending_tasks=2)
    svc = _service(cfg, mock_router, make_transport([]))
    svc._offline_dropped = 3
    svc._intake_dropped = 5
    assert svc._offline is not None
    svc._offline.append(_chat_envelope("q", source_uid="x"))  # depth 1
    d = svc.as_dict()
    assert d == {
        "offline_dropped": 3,
        "offline_queue_depth": 1,
        "intake_dropped": 5,
        "pending_tasks": 0,
    }


def test_as_dict_zero_depth_when_offline_disabled(mock_router, make_transport):
    cfg = NemotronConfig(enabled=True, api_key="k", offline_queue_max=0)
    svc = _service(cfg, mock_router, make_transport([]))
    assert svc.as_dict()["offline_queue_depth"] == 0
