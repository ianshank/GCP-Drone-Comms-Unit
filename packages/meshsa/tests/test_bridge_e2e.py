import asyncio

import pytest

from meshsa import (
    SCHEMA_VERSION,
    CotCodec,
    Envelope,
    JsonCodec,
    LoopbackBus,
    LoopbackTransport,
    MessageKind,
    NodeConfig,
    Position,
    build_node,
)


def _bridge_config() -> NodeConfig:
    return NodeConfig.from_mapping(
        {
            "uid": "base-1",
            "callsign": "BASE1",
            "tier": "base",
            "transports": [
                {"name": "mesh", "type": "loopback", "codec": "json"},
                {"name": "tak", "type": "loopback", "codec": "cot"},
            ],
        }
    )


@pytest.fixture
def bridge_buses() -> tuple[LoopbackBus, LoopbackBus]:
    return LoopbackBus(), LoopbackBus()


async def test_build_node_publishes_position_to_mesh_and_tak(bridge_buses):
    mesh_bus, tak_bus = bridge_buses
    mesh_peer = LoopbackTransport(name="mesh-peer", bus=mesh_bus)
    tak_peer = LoopbackTransport(name="tak-peer", bus=tak_bus)
    node = build_node(
        _bridge_config(),
        transport_kwargs={"mesh": {"bus": mesh_bus}, "tak": {"bus": tak_bus}},
    )

    await node.start()
    try:
        await node.publish_position(Position(lat=12.5, lon=-34.0))
        mesh_frame = await asyncio.wait_for(mesh_peer.stream().__anext__(), timeout=1.0)
        tak_frame = await asyncio.wait_for(tak_peer.stream().__anext__(), timeout=1.0)
    finally:
        await node.stop()

    assert mesh_frame.startswith(b"{")
    assert tak_frame.startswith(b"<event")
    decoded_mesh = JsonCodec().decode(mesh_frame)
    decoded_tak = CotCodec().decode(tak_frame)
    assert decoded_mesh.kind == MessageKind.PLI
    assert decoded_tak.kind == MessageKind.PLI
    assert decoded_mesh.payload["position"]["lat"] == pytest.approx(12.5)
    assert decoded_tak.payload["position"]["lat"] == pytest.approx(12.5)


async def test_build_node_bridges_inbound_cot_to_mesh_json(bridge_buses):
    mesh_bus, tak_bus = bridge_buses
    mesh_peer = LoopbackTransport(name="mesh-peer", bus=mesh_bus)
    tak_injector = LoopbackTransport(name="tak-injector", bus=tak_bus)
    received: list[Envelope] = []
    node = build_node(
        _bridge_config(),
        transport_kwargs={"mesh": {"bus": mesh_bus}, "tak": {"bus": tak_bus}},
    )
    node.on_message(received.append)
    injected = Envelope(
        schema_version=SCHEMA_VERSION,
        msg_id="inj-1",
        ts=1_700_000_000.0,
        source_uid="atak-user",
        kind=MessageKind.PLI,
        payload={
            "node": {"uid": "atak-user", "callsign": "ATAK1"},
            "position": {"lat": 7.5, "lon": 8.25},
        },
    )

    await node.start()
    try:
        await tak_injector.send(CotCodec().encode(injected))
        bridged = await asyncio.wait_for(mesh_peer.stream().__anext__(), timeout=1.0)
    finally:
        await node.stop()

    out = JsonCodec().decode(bridged)
    assert out.kind == MessageKind.PLI
    assert out.payload["position"]["lat"] == pytest.approx(7.5)
    assert out.payload["position"]["lon"] == pytest.approx(8.25)
    assert [env.kind for env in received] == [MessageKind.PLI]


async def test_build_node_publishes_chat_to_mesh_and_tak(bridge_buses):
    mesh_bus, tak_bus = bridge_buses
    mesh_peer = LoopbackTransport(name="mesh-peer", bus=mesh_bus)
    tak_peer = LoopbackTransport(name="tak-peer", bus=tak_bus)
    node = build_node(
        _bridge_config(),
        transport_kwargs={"mesh": {"bus": mesh_bus}, "tak": {"bus": tak_bus}},
    )

    await node.start()
    try:
        await node.publish_chat("hello from base", to="all")
        mesh_frame = await asyncio.wait_for(mesh_peer.stream().__anext__(), timeout=1.0)
        tak_frame = await asyncio.wait_for(tak_peer.stream().__anext__(), timeout=1.0)
    finally:
        await node.stop()

    assert JsonCodec().decode(mesh_frame).payload["text"] == "hello from base"
    cot_chat = CotCodec().decode(tak_frame)
    assert cot_chat.kind == MessageKind.CHAT
    assert cot_chat.payload["text"] == "hello from base"
