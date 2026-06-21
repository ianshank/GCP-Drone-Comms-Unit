import asyncio

import pytest
from aioresponses import aioresponses

from meshsa import (
    JsonCodec,
    LoopbackBus,
    LoopbackTransport,
    MessageKind,
    NodeConfig,
    build_node,
)


@pytest.fixture
def aio_mock():
    with aioresponses() as m:
        yield m


async def test_inference_e2e_bridge(aio_mock):
    # Setup node with loopback transport and inference enabled
    cfg = NodeConfig.from_mapping(
        {
            "uid": "base",
            "callsign": "BASE",
            "transports": [{"name": "mesh", "type": "loopback", "codec": "json"}],
            "inference": {
                "enabled": True,
                "api_key": "test-key",
            },
        }
    )

    bus = LoopbackBus()
    peer = LoopbackTransport(name="peer", bus=bus)
    node = build_node(cfg, transport_kwargs={"mesh": {"bus": bus}})

    aio_mock.post(
        "https://integrate.api.nvidia.com/v1/chat/completions",
        payload={"choices": [{"message": {"content": "Nemotron says hello"}}]},
    )

    await node.start()
    try:
        # Simulate incoming PLI from the mesh
        env_to_send = node._envelope(
            MessageKind.PLI, {"position": {"lat": 1.0, "lon": 1.0}, "node": {"uid": "user1"}}
        )
        env_to_send.source_uid = "user1"

        await peer.send(JsonCodec().encode(env_to_send))

        # We can just iterate the peer's stream with a timeout
        async def wait_for_chat():
            async for data in peer.stream():
                env = JsonCodec().decode(data)
                if env.kind == MessageKind.CHAT and env.source_uid == "base":
                    return env

        env = await asyncio.wait_for(wait_for_chat(), timeout=1.0)
        assert "Nemotron says hello" in env.payload["text"]
        assert env.payload["to"] == "user1"
    finally:
        await node.stop()
