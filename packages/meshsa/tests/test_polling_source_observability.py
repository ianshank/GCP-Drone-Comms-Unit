"""Throttled link-health logging on the polling-source reader thread.

Exercises the observability seam added to ``PollingSourceTransport`` via its
cheapest concrete subclass (``MspSourceTransport``): one ``"source rx"`` line per
``log_every_n`` frames with ``link="up"``, and a ``link="down"`` line after an
idle ``log_interval_s`` window. Logs are emitted from the reader thread, so the
asserts wait for the captured entries with a bounded poll.
"""

import asyncio

import pytest
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


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"log_every_n": 0}, "log_every_n must be >= 1"),
        ({"log_every_n": -1}, "log_every_n must be >= 1"),
        ({"log_interval_s": 0.0}, "log_interval_s must be > 0"),
        ({"log_interval_s": -1.0}, "log_interval_s must be > 0"),
    ],
)
def test_ctor_rejects_invalid_log_throttle(kwargs, match):
    # log_every_n <= 0 would make ``rx_frames % log_every_n`` raise
    # ZeroDivisionError on the reader thread; log_interval_s <= 0 makes the
    # interval comparison meaningless. Both must fail loudly at construction.
    with pytest.raises(ValueError, match=match):
        MspSourceTransport(name="fc", board=object(), poll=_fix_stream(), **kwargs)


async def test_poll_error_during_stop_logs_debug_not_warning():
    # A poll that is blocked inside the link when shutdown begins, then raises
    # because the link was torn down, models a normal stop: it must log at DEBUG,
    # never the WARNING reserved for a genuine in-flight failure. The poll blocks
    # until stop() sets the stop flag, then raises -- so the reader is provably
    # inside _poll when the flag flips.
    import threading

    in_poll = threading.Event()

    def poll(_board):
        in_poll.set()  # signal the reader has entered the (blocking) poll
        # Block until shutdown begins, then raise as a torn-down link would.
        t._stop_event.wait(timeout=2.0)
        raise RuntimeError("link closed during shutdown")

    t = MspSourceTransport(
        name="fc",
        board=object(),
        poll=poll,
        clock=FakeClock(),
        poll_interval_s=0.01,
        log_interval_s=1_000_000.0,
    )
    with structlog.testing.capture_logs() as cap:
        await t.start()
        await asyncio.get_running_loop().run_in_executor(None, in_poll.wait, 2.0)
        await t.stop()

    errors = [e for e in cap if "source poll error" in e["event"]]
    assert errors, "expected the shutdown poll error to be logged"
    assert all(e["log_level"] == "debug" for e in errors)
    assert not any(e["log_level"] == "warning" for e in errors)


async def test_poll_error_while_running_logs_warning():
    # An error while still running (stop flag clear) is a genuine failure and
    # must surface at WARNING so it is not mistaken for a clean stop.
    def poll(_board):
        raise RuntimeError("link died mid-flight")

    t = MspSourceTransport(
        name="fc",
        board=object(),
        poll=poll,
        clock=FakeClock(),
        poll_interval_s=0.01,
        log_interval_s=1_000_000.0,
    )
    with structlog.testing.capture_logs() as cap:
        await t.start()
        await _wait(lambda: any("source poll error" in e["event"] for e in cap))
        await t.stop()

    warnings = [e for e in cap if "source poll error" in e["event"]]
    assert warnings
    assert all(e["log_level"] == "warning" for e in warnings)


async def test_frame_iteration_error_is_guarded():
    # The frame iteration after _poll must run inside the try: a source whose
    # iteration (not just _poll) raises must be caught, not silently kill the
    # thread. Drive the base directly with a _poll returning a generator that
    # raises mid-iteration.
    from meshsa.transports.polling_source import PollingSourceTransport

    class _RaisingSource(PollingSourceTransport):
        _thread_prefix = "raise"

        def _poll(self, _resource):
            def gen():
                yield self._position_frame(0.0, 0.0, 0.0)
                raise RuntimeError("iteration blew up")

            return gen()

    t = _RaisingSource(
        "fc",
        resource=object(),
        factory=lambda: object(),
        source_uid="fc-1",
        clock=FakeClock(),
        poll_wait_s=0.01,
        log_interval_s=1_000_000.0,
    )
    with structlog.testing.capture_logs() as cap:
        await t.start()
        await _wait(lambda: any("source poll error" in e["event"] for e in cap))
        await t.stop()

    errors = [e for e in cap if "source poll error" in e["event"]]
    assert errors  # the iteration error was caught and logged, not swallowed silently
