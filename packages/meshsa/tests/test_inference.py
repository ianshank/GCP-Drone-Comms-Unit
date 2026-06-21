import asyncio

import pytest

from meshsa import (
    Envelope,
    InferenceService,
    MessageKind,
    NemotronClient,
    NemotronConfig,
    SystemClock,
    UuidFactory,
)
from meshsa.inference import _DEFAULT_INSIGHT_PREFIX, _is_ai_insight, _require_aiohttp


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


async def test_nemotron_client_success(aio_mock, env):
    cfg = NemotronConfig(enabled=True, api_key="nvapi-test")
    client = NemotronClient(cfg)

    aio_mock.post(
        "https://integrate.api.nvidia.com/v1/chat/completions",
        payload={"choices": [{"message": {"content": "Test summary"}}]},
    )

    result = await client.analyze(env)
    assert result.summary == "Test summary"


async def test_nemotron_client_disabled(env):
    cfg = NemotronConfig(enabled=False)
    client = NemotronClient(cfg)
    result = await client.analyze(env)
    assert result.summary == ""


async def test_nemotron_client_retry_on_429(aio_mock, env):
    cfg = NemotronConfig(enabled=True, api_key="nvapi-test", max_retries=1)
    client = NemotronClient(cfg)

    # First fails with 429, second succeeds
    aio_mock.post(
        "https://integrate.api.nvidia.com/v1/chat/completions",
        status=429,
    )
    aio_mock.post(
        "https://integrate.api.nvidia.com/v1/chat/completions",
        payload={"choices": [{"message": {"content": "Recovered"}}]},
    )

    result = await client.analyze(env)
    assert result.summary == "Recovered"


async def test_nemotron_client_timeout(aio_mock, env):
    cfg = NemotronConfig(enabled=True, api_key="nvapi-test", timeout_s=0.1, max_retries=0)
    client = NemotronClient(cfg)

    aio_mock.post(
        "https://integrate.api.nvidia.com/v1/chat/completions", exception=asyncio.TimeoutError()
    )

    with pytest.raises(asyncio.TimeoutError):
        await client.analyze(env)


# ── InferenceService ────────────────────────────────────────────────────


async def test_inference_service_publishes_chat(aio_mock, mock_router, env):
    cfg = NemotronConfig(enabled=True, api_key="nvapi-test")
    svc = InferenceService(
        config=cfg,
        router=mock_router,
        clock=SystemClock(),
        id_factory=UuidFactory(),
        source_uid="node-base",
    )

    aio_mock.post(
        "https://integrate.api.nvidia.com/v1/chat/completions",
        payload={"choices": [{"message": {"content": "Insightful observation"}}]},
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


# ── NEW: AI insight feedback loop prevention ────────────────────────────


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


# ── NEW: _running lifecycle guard ───────────────────────────────────────


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


# ── NEW: double-start guard ────────────────────────────────────────────


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


# ── NEW: missing API key logs warning and does not subscribe ────────────


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


# ── NEW: _require_aiohttp guard ─────────────────────────────────────────


def test_require_aiohttp_passes_when_available():
    """Should not raise when aiohttp is installed."""
    _require_aiohttp()


# ── Coverage gap fills ──────────────────────────────────────────────────


async def test_nemotron_client_retries_on_client_error(aio_mock, env):
    """ClientError on final attempt must propagate after logging."""
    import aiohttp as _aiohttp

    cfg = NemotronConfig(enabled=True, api_key="nvapi-test", max_retries=0)
    client = NemotronClient(cfg)

    aio_mock.post(
        "https://integrate.api.nvidia.com/v1/chat/completions",
        exception=_aiohttp.ClientError("connection reset"),
    )

    with pytest.raises(_aiohttp.ClientError):
        await client.analyze(env)


async def test_analyze_and_publish_empty_summary_noop(aio_mock, mock_router, env):
    """When the API returns an empty summary, no message should be published."""
    cfg = NemotronConfig(enabled=True, api_key="nvapi-test")
    svc = InferenceService(
        config=cfg,
        router=mock_router,
        clock=SystemClock(),
        id_factory=UuidFactory(),
        source_uid="node-base",
    )

    aio_mock.post(
        "https://integrate.api.nvidia.com/v1/chat/completions",
        payload={"choices": [{"message": {"content": ""}}]},
    )

    svc.start()
    await mock_router.handlers[0](env)

    for _ in range(200):
        if not svc._bg_tasks:
            break
        await asyncio.sleep(0)
    await svc.stop()

    assert len(mock_router.published) == 0


async def test_analyze_and_publish_exception_logged(aio_mock, mock_router, env):
    """When the API call fails, the exception should be caught and logged."""
    import aiohttp as _aiohttp

    cfg = NemotronConfig(enabled=True, api_key="nvapi-test", max_retries=0)
    svc = InferenceService(
        config=cfg,
        router=mock_router,
        clock=SystemClock(),
        id_factory=UuidFactory(),
        source_uid="node-base",
    )

    aio_mock.post(
        "https://integrate.api.nvidia.com/v1/chat/completions",
        exception=_aiohttp.ClientError("boom"),
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


async def test_nemotron_client_no_api_key_returns_empty(env):
    """When api_key is empty but enabled is True, analyze returns empty result."""
    cfg = NemotronConfig(enabled=True, api_key="")
    client = NemotronClient(cfg)
    result = await client.analyze(env)
    assert result.summary == ""
    assert result.raw_response == ""


# ── Server error and malformed response tests ───────────────────────────


async def test_nemotron_client_500_error_raises(aio_mock, env):
    """5xx server errors should propagate as ClientResponseError."""
    import aiohttp as _aiohttp

    cfg = NemotronConfig(enabled=True, api_key="nvapi-test", max_retries=0)
    client = NemotronClient(cfg)

    aio_mock.post(
        "https://integrate.api.nvidia.com/v1/chat/completions",
        status=500,
    )

    with pytest.raises(_aiohttp.ClientResponseError):
        await client.analyze(env)


async def test_nemotron_client_malformed_json_key_error(aio_mock, env):
    """Missing 'choices' key in response should propagate as KeyError."""
    cfg = NemotronConfig(enabled=True, api_key="nvapi-test", max_retries=0)
    client = NemotronClient(cfg)

    aio_mock.post(
        "https://integrate.api.nvidia.com/v1/chat/completions",
        payload={"error": "unexpected format"},
    )

    with pytest.raises(KeyError):
        await client.analyze(env)


async def test_nemotron_client_empty_choices_index_error(aio_mock, env):
    """Empty 'choices' array in response should propagate as IndexError."""
    cfg = NemotronConfig(enabled=True, api_key="nvapi-test", max_retries=0)
    client = NemotronClient(cfg)

    aio_mock.post(
        "https://integrate.api.nvidia.com/v1/chat/completions",
        payload={"choices": []},
    )

    with pytest.raises(IndexError):
        await client.analyze(env)


# ── Injectable sleep and configurable backoff ─────────────────────────


async def test_nemotron_client_uses_injectable_sleep_and_backoff_base(aio_mock, env):
    """Custom sleep and backoff_base should be used during 429 retries."""
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    cfg = NemotronConfig(enabled=True, api_key="nvapi-test", max_retries=2, backoff_base=3.0)
    client = NemotronClient(cfg, sleep=fake_sleep)

    # Fail twice with 429, then succeed
    aio_mock.post(
        "https://integrate.api.nvidia.com/v1/chat/completions",
        status=429,
    )
    aio_mock.post(
        "https://integrate.api.nvidia.com/v1/chat/completions",
        status=429,
    )
    aio_mock.post(
        "https://integrate.api.nvidia.com/v1/chat/completions",
        payload={"choices": [{"message": {"content": "Finally"}}]},
    )

    result = await client.analyze(env)
    assert result.summary == "Finally"
    # backoff_base=3.0: sleep(3**0)=1.0, sleep(3**1)=3.0
    assert sleeps == [1.0, 3.0]


async def test_nemotron_client_injectable_sleep_on_transient_error(aio_mock, env):
    """Injectable sleep should be used during transient error retries too."""
    import aiohttp as _aiohttp

    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    cfg = NemotronConfig(enabled=True, api_key="nvapi-test", max_retries=1, backoff_base=2.0)
    client = NemotronClient(cfg, sleep=fake_sleep)

    # First attempt: transient error, second: success
    aio_mock.post(
        "https://integrate.api.nvidia.com/v1/chat/completions",
        exception=_aiohttp.ClientError("transient"),
    )
    aio_mock.post(
        "https://integrate.api.nvidia.com/v1/chat/completions",
        payload={"choices": [{"message": {"content": "OK"}}]},
    )

    result = await client.analyze(env)
    assert result.summary == "OK"
    # backoff_base=2.0: sleep(2**0)=1.0
    assert sleeps == [1.0]
