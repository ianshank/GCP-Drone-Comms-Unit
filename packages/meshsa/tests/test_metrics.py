"""Router observability counters (rx/tx/forwarded/drops/schema_mismatch)."""

import asyncio

from meshsa import (
    Envelope,
    JsonCodec,
    LoopbackBus,
    LoopbackTransport,
    MessageKind,
    Router,
    RouterMetrics,
    render_prometheus,
)


def _env(mid, schema=1):
    return Envelope(
        schema_version=schema,
        msg_id=mid,
        ts=1.0,
        source_uid="u",
        kind=MessageKind.CHAT,
        payload={"text": "hi", "to": None},
    )


async def test_publish_increments_tx_per_transport():
    bus = LoopbackBus()
    r = Router(
        [LoopbackTransport(name="a", bus=bus), LoopbackTransport(name="b", bus=bus)], JsonCodec()
    )
    await r.publish(_env("m1"))
    assert r.metrics.tx == 2


async def test_pump_counts_rx_forwarded_and_drops():
    bus_a, bus_b = LoopbackBus(), LoopbackBus()
    src = LoopbackTransport(name="src", bus=bus_a)
    dst = LoopbackTransport(name="dst", bus=bus_b)
    feeder = LoopbackTransport(name="feeder", bus=bus_a)  # injects into src only
    r = Router([src, dst], JsonCodec())
    await r.start()
    await feeder.send(JsonCodec().encode(_env("rx1")))  # valid -> rx + forwarded to dst
    await feeder.send(b"not-json")  # malformed -> dropped_undecodable
    await feeder.send(JsonCodec().encode(_env("bad", schema=99)))  # -> schema_mismatch
    await asyncio.sleep(0.05)
    await r.stop()
    assert r.metrics.rx == 1
    assert r.metrics.forwarded == 1
    assert r.metrics.dropped_undecodable == 1
    assert r.metrics.schema_mismatch == 1


def test_as_dict_round_trips_counters():
    m = RouterMetrics(rx=1, tx=2, forwarded=3, dropped_undecodable=4, schema_mismatch=5)
    assert m.as_dict() == {
        "rx": 1,
        "tx": 2,
        "forwarded": 3,
        "dropped_undecodable": 4,
        "schema_mismatch": 5,
    }
    # Reconstructing from the dict yields an equal dataclass (true round-trip).
    assert RouterMetrics(**m.as_dict()) == m


def test_render_prometheus_with_populated_transports():
    m = RouterMetrics(rx=7, tx=3, forwarded=2, dropped_undecodable=1, schema_mismatch=4)
    text = render_prometheus(
        m,
        {"radio": {"dropped_inbox_full": 5, "reconnects": 2, "rx_frames": 9}},
    )
    lines = text.splitlines()
    assert "meshsa_rx_total 7" in lines
    assert "meshsa_tx_total 3" in lines
    assert "meshsa_forwarded_total 2" in lines
    assert "meshsa_dropped_undecodable_total 1" in lines
    assert "meshsa_schema_mismatch_total 4" in lines
    assert 'meshsa_transport_dropped_inbox_full{transport="radio"} 5' in lines
    assert 'meshsa_transport_reconnects{transport="radio"} 2' in lines
    assert 'meshsa_transport_rx_frames{transport="radio"} 9' in lines
    assert text.endswith("\n")


def test_render_prometheus_with_empty_transports():
    text = render_prometheus(RouterMetrics(), {})
    lines = text.splitlines()
    # Only the five router-level series; no per-transport lines.
    assert lines == [
        "meshsa_rx_total 0",
        "meshsa_tx_total 0",
        "meshsa_forwarded_total 0",
        "meshsa_dropped_undecodable_total 0",
        "meshsa_schema_mismatch_total 0",
    ]


def test_render_prometheus_transport_missing_rx_frames_defaults_zero():
    # A transport dict without rx_frames exercises the getattr/default path.
    text = render_prometheus(RouterMetrics(), {"tak": {"dropped_inbox_full": 0, "reconnects": 0}})
    assert 'meshsa_transport_rx_frames{transport="tak"} 0' in text.splitlines()


def test_render_prometheus_escapes_special_chars_in_transport_name():
    # Transport names are user-configurable, so a name with a backslash, quote and
    # newline must be escaped per the text-exposition spec (\\ \" \n) so the line
    # stays a single, valid, parseable series rather than breaking the format.
    raw = 'a\\b"c\nd'
    text = render_prometheus(RouterMetrics(rx=1), {raw: {"rx_frames": 9}})
    lines = text.splitlines()
    # Spec escaping: \\ -> \\\\ , " -> \" , newline -> \n (literal backslash + n).
    escaped = 'a\\\\b\\"c\\nd'
    expected = f'meshsa_transport_rx_frames{{transport="{escaped}"}} 9'
    assert expected in lines
    # The raw newline in the name must not survive into the output: every series
    # stays on one physical line, so the line count is exactly 5 router + 3
    # per-transport rather than splitting the name across two lines.
    assert len(lines) == 8
    assert all("\n" not in line for line in lines)
