"""Link-loss resilience soak (docs/specs/m2-soak-fuzz.md, ROADMAP M2 "soak/fuzz").

Link-layer denial (802.11-class deauthentication, jamming, radio dropout) is an
*availability* attack that TLS and endpoint auth cannot stop. What must hold when the
link dies mid-stream is fail-closed behavior with bounded retries and clean recovery:

* the heartbeat-driven pre-arm interlock (``HeartbeatHealth``) denies arming the
  moment heartbeats go stale, and recovers only on a fresh beat;
* the send pacer (``Pacer``) never exceeds its configured sustained rate under a
  flood, so a reconnect burst cannot become a send storm;
* the reconnect ``Backoff`` grows to its cap and stays there (bounded attempt rate,
  no runaway), and resets cleanly after a successful reconnect.

Everything runs on injected fake clocks/sleeps — thousands of simulated link cycles,
no real waiting — so the soak is deterministic and cheap enough for every CI run;
``slow`` marks the long fuzz variants for the nightly workflow. On-radio validation
(real deauth against the bench link) is tracked in docs/specs/m2-soak-fuzz.md §Bench.
"""

from __future__ import annotations

import random

import pytest

from meshsa.command.health import HeartbeatHealth
from meshsa.transports.backoff import Backoff
from meshsa.transports.pacing import Pacer

#: Soak scale for the per-PR run; the nightly fuzz multiplies this out.
LINK_CYCLES = 500
FUZZ_CYCLES = 5_000
#: Interlock freshness window (mirrors HeartbeatHealth's default shape, set explicitly).
HEARTBEAT_MAX_AGE_S = 2.0
#: Pacer profile: the FTS-facing shape (sustained cap with a small burst allowance).
PACER_RATE_HZ = 10.0
PACER_BURST = 5
#: Reconnect schedule mirroring the TAK/Meshtastic supervisors' config shape.
BACKOFF_INITIAL_S = 0.5
BACKOFF_MAX_S = 30.0
BACKOFF_FACTOR = 2.0


class ManualClock:
    """Monotonic fake clock advanced explicitly by the test (no auto-step)."""

    def __init__(self, start: float = 0.0) -> None:
        self.t = start

    def now(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


class RecordingSleep:
    """Async sleep fake that records delays and advances the shared clock."""

    def __init__(self, clock: ManualClock) -> None:
        self._clock = clock
        self.delays: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)
        self._clock.advance(delay)


# ---- heartbeat interlock: fail closed on drop, recover on beat -------------
def test_heartbeat_interlock_fails_closed_and_recovers_over_many_link_cycles():
    clock = ManualClock()
    health = HeartbeatHealth(clock, max_age_s=HEARTBEAT_MAX_AGE_S)

    assert health() is None  # never armed before the first beat: fail closed from birth

    for cycle in range(LINK_CYCLES):
        # Live link: beats every 1s stay comfortably inside the freshness window.
        for _ in range(3):
            health.beat()
            clock.advance(1.0)
            report = health()
            assert report is not None and report.arm_permitted, f"cycle {cycle}: live link denied"

        # Sudden link loss (deauth/jam): silence past the window must deny arming.
        clock.advance(HEARTBEAT_MAX_AGE_S + 0.1)
        report = health()
        assert report is not None
        assert not report.arm_permitted, f"cycle {cycle}: stale link still armable"
        assert report.reasons == ("heartbeat_stale",)

        # Arbitrarily long outage never flips it back open.
        clock.advance(60.0)
        stale = health()
        assert stale is not None and not stale.arm_permitted

        # Clean recovery: one fresh beat restores arm permission.
        health.beat()
        recovered = health()
        assert recovered is not None and recovered.arm_permitted, f"cycle {cycle}: no recovery"


# ---- pacer: a reconnect flood never becomes a send storm -------------------
async def test_pacer_bounds_sustained_rate_under_flood():
    clock = ManualClock()
    sleep = RecordingSleep(clock)
    pacer = Pacer(rate_hz=PACER_RATE_HZ, burst=PACER_BURST, clock=clock, sleep=sleep)

    sends = PACER_BURST + LINK_CYCLES  # burst drain + a long backlog flush
    start = clock.now()
    for _ in range(sends):
        await pacer.acquire()
    elapsed = clock.now() - start

    # Everything past the burst allowance must have paid for a token: the sustained
    # rate over the flood can never exceed rate_hz (no storm on reconnect flush).
    assert elapsed >= (sends - PACER_BURST) / PACER_RATE_HZ
    # And the pacer never over-waits: each pause is at most one token interval.
    assert sleep.delays and max(sleep.delays) <= 1.0 / PACER_RATE_HZ + 1e-9
    assert min(sleep.delays) >= 0.0


async def test_pacer_survives_clock_stall_and_backward_jump():
    # A link stall long enough to fully refill the bucket, then a non-monotonic
    # backward jump: neither may produce a burst beyond capacity or a huge sleep.
    clock = ManualClock()
    sleep = RecordingSleep(clock)
    pacer = Pacer(rate_hz=PACER_RATE_HZ, burst=PACER_BURST, clock=clock, sleep=sleep)

    clock.advance(3_600.0)  # long stall: refill is capped at burst, not 36k tokens
    for _ in range(PACER_BURST):
        await pacer.acquire()
    assert sleep.delays == []  # exactly the burst passes free

    clock.t -= 100.0  # wall-clock misbehavior; the pacer must clamp, not storm
    await pacer.acquire()
    assert len(sleep.delays) == 1
    assert 0.0 <= sleep.delays[0] <= 1.0 / PACER_RATE_HZ + 1e-9


# ---- backoff: bounded retry schedule, clean reset on reconnect -------------
async def test_backoff_caps_retry_rate_and_resets_cleanly():
    clock = ManualClock()
    sleep = RecordingSleep(clock)
    backoff = Backoff(
        initial_s=BACKOFF_INITIAL_S, max_s=BACKOFF_MAX_S, factor=BACKOFF_FACTOR, sleep=sleep
    )

    # A long outage: delays must climb to the cap and hold there — the attempt rate
    # is bounded by 1/max_s, never unbounded.
    for _ in range(LINK_CYCLES):
        await backoff.sleep_and_advance()
    assert backoff.current == BACKOFF_MAX_S
    assert max(sleep.delays) == BACKOFF_MAX_S
    tail = sleep.delays[-10:]
    assert all(d == BACKOFF_MAX_S for d in tail), "retry schedule must saturate, not oscillate"

    # Clean recovery: reset returns to the initial delay for the next outage.
    backoff.reset()
    assert backoff.current == BACKOFF_INITIAL_S


@pytest.mark.slow
async def test_fuzzed_link_cycles_keep_interlock_and_backoff_consistent():
    """Nightly fuzz: random outage/recovery timings never wedge the gate or the schedule."""
    rng = random.Random(0x4D32)  # fixed seed ("M2"): deterministic soak
    clock = ManualClock()
    sleep = RecordingSleep(clock)
    health = HeartbeatHealth(clock, max_age_s=HEARTBEAT_MAX_AGE_S)
    backoff = Backoff(
        initial_s=BACKOFF_INITIAL_S, max_s=BACKOFF_MAX_S, factor=BACKOFF_FACTOR, sleep=sleep
    )

    for _ in range(FUZZ_CYCLES):
        up_beats = rng.randint(1, 5)
        for _ in range(up_beats):
            health.beat()
            clock.advance(rng.uniform(0.0, HEARTBEAT_MAX_AGE_S))  # always fresh
            report = health()
            assert report is not None and report.arm_permitted
        backoff.reset()  # link was up: supervisor resets its schedule

        outage = rng.uniform(HEARTBEAT_MAX_AGE_S + 0.01, 120.0)
        clock.advance(outage)
        report = health()
        assert report is not None and not report.arm_permitted  # fail closed, always
        retries = rng.randint(1, 12)
        for _ in range(retries):
            await backoff.sleep_and_advance()
        assert BACKOFF_INITIAL_S <= backoff.current <= BACKOFF_MAX_S

    assert max(sleep.delays) <= BACKOFF_MAX_S  # no delay ever exceeded the cap
