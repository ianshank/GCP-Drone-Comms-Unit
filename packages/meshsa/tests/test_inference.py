import asyncio

import pytest
from aioresponses import aioresponses

from meshsa import (
    Envelope,
    InferenceService,
    MessageKind,
    NemotronClient,
    NemotronConfig,
    SystemClock,
    UuidFactory,
)
from meshsa.inference import _AI_INSIGHT_PREFIX, _is_ai_insight, _require_aiohttp


@pytest.fixture
def aio_mock():
    with aioresponses() as m:
        yield m


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
        payload={"text": f"{_AI_INSIGHT_PREFIX} Summary of something"},
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
        payload={"text": f"{_AI_INSIGHT_PREFIX} some text"},
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
