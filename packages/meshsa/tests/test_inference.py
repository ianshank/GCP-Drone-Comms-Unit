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

    # Yield to let the bg task run
    await asyncio.sleep(0.01)
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
