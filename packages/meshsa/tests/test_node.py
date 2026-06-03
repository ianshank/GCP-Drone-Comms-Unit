import asyncio

from meshsa import LoopbackBus, MessageKind, NodeConfig, NodeTier, Position, build_node


def _cfg(uid, tier="user"):
    return NodeConfig(
        uid=uid, callsign=uid.upper(), tier=tier, transports=[{"name": "mesh", "type": "loopback"}]
    )


def test_build_node_skips_unknown_and_disabled(clock, ids):
    cfg = NodeConfig(
        uid="u",
        callsign="U",
        transports=[
            {"name": "good", "type": "loopback"},
            {"name": "future", "type": "halow-v2"},  # unknown -> skipped, not fatal
            {"name": "off", "type": "loopback", "enabled": False},
        ],
    )
    node = build_node(cfg, clock=clock, id_factory=ids)
    assert len(node.router.transports) == 1
    assert node.info.tier == NodeTier.USER


async def test_two_nodes_exchange_position_over_shared_bus(clock, ids):
    bus = LoopbackBus()
    tk = {"mesh": {"bus": bus}}
    a = build_node(_cfg("a"), clock=clock, id_factory=ids, transport_kwargs=tk)
    b = build_node(_cfg("b"), clock=clock, id_factory=ids, transport_kwargs=tk)
    inbox = []
    b.on_message(lambda e: inbox.append(e))
    await a.start()
    await b.start()
    env = await a.publish_position(Position(lat=37.0, lon=-122.0))
    await asyncio.sleep(0.05)
    await a.stop()
    await b.stop()
    assert len(inbox) == 1
    assert inbox[0].kind == MessageKind.PLI
    assert inbox[0].source_uid == "a"
    assert inbox[0].payload["position"]["lat"] == 37.0
    assert env.msg_id.startswith("id-")


async def test_publish_chat_builds_envelope(clock, ids):
    node = build_node(_cfg("c"), clock=clock, id_factory=ids)
    await node.start()
    env = await node.publish_chat("status green", to="b")
    await node.stop()
    assert env.kind == MessageKind.CHAT
    assert env.payload == {"text": "status green", "to": "b"}


def test_build_node_per_transport_codec():
    cfg = NodeConfig(
        uid="b",
        callsign="BASE",
        tier="base",
        transports=[
            {"name": "mesh", "type": "loopback"},
            {"name": "tak", "type": "loopback", "codec": "cot", "codec_options": {"stale_s": 60.0}},
        ],
    )
    node = build_node(cfg)
    assert "tak" in node.router.codecs
    assert node.router.codecs["tak"].stale_s == 60.0


def test_router_queue_maxsize_wires_to_transport_inbox():
    # RouterConfig.queue_maxsize was dead config; build_node now applies it.
    cfg = NodeConfig(
        uid="u",
        callsign="U",
        router={"queue_maxsize": 7},
        transports=[{"name": "mesh", "type": "loopback"}],
    )
    node = build_node(cfg)
    assert node.router.transports[0]._inbox.maxsize == 7


def test_transport_option_overrides_router_queue_maxsize():
    cfg = NodeConfig(
        uid="u",
        callsign="U",
        router={"queue_maxsize": 7},
        transports=[{"name": "mesh", "type": "loopback", "options": {"queue_maxsize": 3}}],
    )
    node = build_node(cfg)
    assert node.router.transports[0]._inbox.maxsize == 3


def test_build_node_forwards_mesh_config_to_meshtastic():
    # MeshConfig was dead config; build_node now threads it to the radio transport.
    cfg = NodeConfig(
        uid="u",
        callsign="U",
        mesh={"region": "EU", "channel": "ops", "freq_khz": 906500},
        transports=[{"name": "lora", "type": "meshtastic", "options": {"connection": "serial"}}],
    )
    node = build_node(cfg)
    assert node.router.transports[0]._mesh == {
        "channel": "ops",
        "psk": None,
        "region": "EU",
        "freq_khz": 906500,
    }


def test_build_node_accepts_injected_codec_instance():
    from meshsa import CotCodec

    cfg = NodeConfig(
        uid="b", callsign="B", tier="base", transports=[{"name": "tak", "type": "loopback"}]
    )
    node = build_node(cfg, codec_instances={"tak": CotCodec(stale_s=42.0)})
    assert node.router.codecs["tak"].stale_s == 42.0  # injected instance wins
