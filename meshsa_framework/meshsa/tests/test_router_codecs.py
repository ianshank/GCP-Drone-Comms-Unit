import asyncio

from meshsa import (CotCodec, Envelope, JsonCodec, LoopbackBus, LoopbackTransport,
                    MessageKind, Router)


def _pli(mid):
    return Envelope(msg_id=mid, ts=1_700_000_000.0, source_uid="u",
                    kind=MessageKind.PLI,
                    payload={"node": {"callsign": "FOX"},
                             "position": {"lat": 1.0, "lon": 2.0}})


async def test_publish_encodes_per_transport_codec():
    json_t = LoopbackTransport(name="mesh")
    cot_t = LoopbackTransport(name="tak")
    r = Router([json_t, cot_t], JsonCodec(), codecs={"tak": CotCodec()})
    await r.publish(_pli("m1"))
    assert json_t.sent[0].startswith(b"{")          # JSON on the mesh side
    assert cot_t.sent[0].startswith(b"<event")      # CoT on the TAK side


async def test_bridge_translates_cot_to_json():
    bus_tak, bus_mesh = LoopbackBus(), LoopbackBus()
    tak = LoopbackTransport(name="tak", bus=bus_tak)
    mesh = LoopbackTransport(name="mesh", bus=bus_mesh)
    injector = LoopbackTransport(name="inj", bus=bus_tak)   # an ATAK/FTS peer
    listener = LoopbackTransport(name="lst", bus=bus_mesh)  # a mesh peer
    r = Router([tak, mesh], JsonCodec(), codecs={"tak": CotCodec()})
    await r.start()
    await injector.send(CotCodec().encode(_pli("m2")))       # CoT arrives from TAK
    got = await asyncio.wait_for(listener.stream().__anext__(), timeout=1.0)
    await r.stop()
    out = JsonCodec().decode(got)                            # forwarded as JSON
    assert out.kind == MessageKind.PLI
    assert out.payload["position"]["lat"] == 1.0
