import asyncio

from meshsa import (
    HttpResponse,
    JsonCodec,
    LoopbackBus,
    LoopbackTransport,
    MessageKind,
    NodeConfig,
    build_node,
)


async def test_inference_e2e_bridge(make_transport):
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
    # Inject the fake HTTP transport into the inference service the node builds.
    inference_transport = make_transport(
        [
            HttpResponse(
                status=200, payload={"choices": [{"message": {"content": "Nemotron says hello"}}]}
            )
        ],
        repeat_last=True,
    )
    node = build_node(
        cfg,
        transport_kwargs={"mesh": {"bus": bus}},
        inference_transport=inference_transport,
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
