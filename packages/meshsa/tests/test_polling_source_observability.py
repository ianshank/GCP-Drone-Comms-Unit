"""Throttled link-health logging on the polling-source reader thread.

Exercises the observability seam added to ``PollingSourceTransport`` via its
cheapest concrete subclass (``MspSourceTransport``): one ``"source rx"`` line per
``log_every_n`` frames with ``link="up"``, and a ``link="down"`` line after an
idle ``log_interval_s`` window. Logs are emitted from the reader thread, so the
asserts wait for the captured entries with a bounded poll.
"""

import asyncio

import structlog
from conftest import FakeClock

from meshsa import MspSourceTransport


def _fix_stream(*fixes):
    """A poll() that yields each fix once, then ``None`` (no fix) forever."""
    seq = list(fixes)

    def poll(_board):
        return seq.pop(0) if seq else None

    return poll


async def _wait(cond, tries: int = 400) -> None:
    for _ in range(tries):
        if cond():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("condition not met in time")


def _source_rx(entries):
    return [e for e in entries if e["event"] == "source rx"]


async def test_emits_one_up_line_per_log_every_n_frames():
    n = 3
    fixes = [{"lat": i, "lon": i, "alt": 0} for i in range(n)]
    t = MspSourceTransport(
        name="fc",
        board=object(),
        poll=_fix_stream(*fixes),
        clock=FakeClock(),
        poll_interval_s=0.01,
        log_every_n=n,
        log_interval_s=1_000_000.0,  # huge: only the frame-count branch can fire
    )
    with structlog.testing.capture_logs() as cap:
        await t.start()
        try:
            await _wait(lambda: len(_source_rx(cap)) >= 1)
        finally:
            await t.stop()
        ups = _source_rx(cap)

    assert len(ups) == 1
    entry = ups[0]
    assert entry["transport"] == "fc"
    assert entry["rx"] == n
    assert entry["link"] == "up"
    assert entry["dropped_inbox_full"] == 0


async def test_emits_down_line_on_idle_after_interval():
    # No fixes ever -> idle poll cycles. FakeClock advances 1.0 per now() call,
    # so a 2.0s interval trips within a couple of idle cycles -> link="down".
    t = MspSourceTransport(
        name="fc",
        board=object(),
        poll=_fix_stream(),  # always None
        clock=FakeClock(),
        poll_interval_s=0.01,
        log_every_n=100,
        log_interval_s=2.0,
    )
    with structlog.testing.capture_logs() as cap:
        await t.start()
        try:
            await _wait(lambda: any(e["link"] == "down" for e in _source_rx(cap)))
        finally:
            await t.stop()
        downs = [e for e in _source_rx(cap) if e["link"] == "down"]

    assert downs  # at least one idle-timeout line
    assert downs[0]["transport"] == "fc"
    assert downs[0]["rx"] == 0
