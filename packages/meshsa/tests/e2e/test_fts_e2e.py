"""FTS end-to-end harness, in two parts.

Part 1 (hardware-free, always runs): builds a PLI/position :class:`Envelope` the
same way ``tests/test_tak.py`` and ``tests/test_bridge_e2e.py`` do, encodes it
with the real :class:`~meshsa.cot.CotCodec`, and asserts the produced CoT
``<event>`` frame both round-trips through ``CotCodec.decode`` and survives a
split byte stream reassembled by the real :class:`~meshsa.transports.tak.CotFramer`
(the same framer ``TakTcpTransport`` uses on its read path). This gives real,
always-on coverage of the encode/decode + framing path with no sockets and no
live FreeTAKServer.

Part 2 (live-FTS, hardware-deferred): opt-in only via ``MESHSA_FTS_E2E=1`` with
an FTS on ``:8087``. It connects a real ``TakTcpTransport``, sends the same kind
of PLI, and asserts the track echoes back on the multicast CoT group
(``239.2.3.1:6969`` via ``TakMulticastTransport``). Skipped by default so it can
never affect the coverage gate. Executed by ``.github/workflows/fts-e2e.yml`` on
a self-hosted Jetson runner.
"""

from __future__ import annotations

import os

import pytest

from meshsa import CotCodec, Envelope, MessageKind
from meshsa.transports.tak import CotFramer

pytestmark = pytest.mark.e2e

_ENABLED = os.environ.get("MESHSA_FTS_E2E") == "1"


def _pli_envelope(uid: str = "drone-1") -> Envelope:
    """Build a PLI/position Envelope the same way test_tak.py's ``_cot_pli`` and
    test_bridge_e2e.py's fixtures do: a minimal ``node``/``position`` payload."""
    return Envelope(
        msg_id="fts-e2e-1",
        ts=1_700_000_000.0,
        source_uid=uid,
        kind=MessageKind.PLI,
        payload={
            "node": {"callsign": "DRONE1"},
            "position": {"lat": 37.0, "lon": -122.0, "hae": 15.0},
        },
    )


# =================== Part 1: hardware-free (always runs) ===================
def test_pli_encodes_to_cot_event_and_round_trips() -> None:
    """Offline-verifiable half: real CotCodec encode -> decode, no sockets."""
    env = _pli_envelope()
    frame = CotCodec().encode(env)

    assert frame.startswith(b"<event")

    decoded = CotCodec().decode(frame)
    assert decoded.kind == MessageKind.PLI
    assert decoded.source_uid == env.source_uid
    assert decoded.payload["position"]["lat"] == pytest.approx(37.0)
    assert decoded.payload["position"]["lon"] == pytest.approx(-122.0)


def test_pli_cot_event_survives_split_stream_via_cot_framer() -> None:
    """The same framing TakTcpTransport uses on its read path: a CoT frame split
    mid-event across two TCP chunks must reassemble to one complete <event> that
    decodes back to our PLI, with no transport/socket involved."""
    frame = CotCodec().encode(_pli_envelope("drone-2"))
    framer = CotFramer()

    # Feed the frame in two pieces, mirroring the partial-read case exercised by
    # test_tak.py's test_tcp_receive_frames_and_ingests.
    split = len(frame) // 2
    assert framer.feed(frame[:split]) == []  # partial -> buffered, nothing yet
    events = framer.feed(frame[split:])  # completes the event

    assert len(events) == 1
    assert events[0].startswith(b"<event")
    assert events[0].endswith(b"</event>")

    decoded = CotCodec().decode(events[0])
    assert decoded.kind == MessageKind.PLI
    assert decoded.source_uid == "drone-2"


# ============ Part 2: live-FTS (hardware-deferred, opt-in only) ============
@pytest.mark.skipif(not _ENABLED, reason="set MESHSA_FTS_E2E=1 with a live FTS on :8087")
@pytest.mark.asyncio
async def test_pli_roundtrips_through_live_fts() -> None:
    """Connects a real TakTcpTransport to FTS, sends one PLI, and asserts the
    track echoes back on the multicast CoT group. Never runs in the standard
    gate (guarded skip) so it cannot affect line coverage or require hardware
    at import time -- all socket/multicast imports are function-local here."""
    import asyncio

    from meshsa.transports.tak import TakMulticastTransport, TakTcpTransport

    host = os.environ.get("MESHSA_FTS_HOST", "127.0.0.1")
    port = int(os.environ.get("MESHSA_FTS_TCP_PORT", "8087"))
    mc_group = os.environ.get("MESHSA_FTS_MC_GROUP", "239.2.3.1")
    mc_port = int(os.environ.get("MESHSA_FTS_MC_PORT", "6969"))

    env = _pli_envelope("live-fts-drone")
    frame = CotCodec().encode(env)

    tcp = TakTcpTransport(name="tak", host=f"tcp://{host}:{port}")
    multicast = TakMulticastTransport(name="tak-mc", group=mc_group, port=mc_port)

    await tcp.start()
    await multicast.start()
    try:
        await tcp.send(frame)

        found = None
        deadline = asyncio.get_event_loop().time() + 10.0
        while asyncio.get_event_loop().time() < deadline:
            try:
                candidate = await asyncio.wait_for(multicast.stream().__anext__(), timeout=1.0)
            except TimeoutError:
                continue
            decoded = CotCodec().decode(candidate)
            if decoded.source_uid == env.source_uid:
                found = decoded
                break

        assert found is not None, "PLI did not echo back on the multicast group within 10s"
        assert found.kind == MessageKind.PLI
        assert found.payload["position"]["lat"] == pytest.approx(37.0)
    finally:
        await tcp.stop()
        await multicast.stop()
