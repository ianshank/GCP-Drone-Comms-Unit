"""``meshsa.inference.service`` tests: InferenceService's pub/sub lifecycle,
AI-insight feedback-loop prevention, rate limiting (``_RateGate``), the offline
replay queue (``_OfflineQueue``), task-intake backpressure, and ``as_dict()``.

Private-attribute assertions below (``svc._rate_gate._semaphore``,
``svc._offline_queue._queue``/``._dropped``) reach into the ``_RateGate``/
``_OfflineQueue`` collaborators extracted from ``InferenceService`` in
code-hygiene-modularity T-4.1a — white-box by design.
"""

import asyncio

import pytest

from meshsa import (
    Envelope,
    HttpResponse,
    InferenceService,
    InferenceTransportError,
    MessageKind,
    NemotronConfig,
    SystemClock,
    UuidFactory,
)
from meshsa.inference.service import _DEFAULT_INSIGHT_PREFIX, _is_ai_insight


def _ok(content: str) -> HttpResponse:
    """A 200 response shaped like the NIM chat-completions payload."""
    return HttpResponse(status=200, payload={"choices": [{"message": {"content": content}}]})


@pytest.fixture
def env():
    return Envelope(
        schema_version=1,
        msg_id="msg-1",
        ts=1.0,
        source_uid="node-a",
        kind=MessageKind.PLI,
        payload={"position": {"lat": 1.0, "lon": 2.0}},
    )


@pytest.fixture
def mock_router():
    class MockRouter:
        def __init__(self):
            self.handlers = []
            self.published = []

        def subscribe(self, handler):
            self.handlers.append(handler)

        async def publish(self, envelope):
            self.published.append(envelope)

    return MockRouter()


async def test_inference_service_publishes_chat(make_transport, mock_router, env):
    cfg = NemotronConfig(enabled=True, api_key="nvapi-test")
    svc = InferenceService(
        config=cfg,
        router=mock_router,
        clock=SystemClock(),
        id_factory=UuidFactory(),
        source_uid="node-base",
        transport=make_transport([_ok("Insightful observation")]),
    )

    svc.start()
    assert len(mock_router.handlers) == 1

    # Simulate inbound message
    await mock_router.handlers[0](env)

    # Bounded retry — wait until the bg task publishes rather than fixed sleep
    for _ in range(200):
        if mock_router.published:
            break
        await asyncio.sleep(0)
    await svc.stop()

    assert len(mock_router.published) == 1
    reply = mock_router.published[0]
    assert reply.kind == MessageKind.CHAT
    assert reply.source_uid == "node-base"
    assert reply.payload["to"] == "node-a"
    assert "Insightful observation" in reply.payload["text"]


async def test_inference_service_ignores_own_messages(mock_router):
    cfg = NemotronConfig(enabled=True, api_key="nvapi-test")
    svc = InferenceService(
        config=cfg,
        router=mock_router,
        clock=SystemClock(),
        id_factory=UuidFactory(),
        source_uid="node-base",
    )
    svc.start()

    env = Envelope(
        schema_version=1,
        msg_id="self-msg",
        ts=1.0,
        source_uid="node-base",  # Same as service source_uid
        kind=MessageKind.CHAT,
        payload={"text": "hello"},
    )

    await mock_router.handlers[0](env)
    assert len(svc._bg_tasks) == 0  # Task was not spawned


# ── AI insight feedback loop prevention ─────────────────────────────────


async def test_inference_service_ignores_ai_insights(mock_router):
    """Messages prefixed with [AI Insight] must be silently dropped."""
    cfg = NemotronConfig(enabled=True, api_key="nvapi-test")
    svc = InferenceService(
        config=cfg,
        router=mock_router,
        clock=SystemClock(),
        id_factory=UuidFactory(),
        source_uid="node-base",
    )
    svc.start()

    insight_env = Envelope(
        schema_version=1,
        msg_id="ai-loop-msg",
        ts=2.0,
        source_uid="node-other",
        kind=MessageKind.CHAT,
        payload={"text": f"{_DEFAULT_INSIGHT_PREFIX} Summary of something"},
    )

    await mock_router.handlers[0](insight_env)
    assert len(svc._bg_tasks) == 0


def test_is_ai_insight_true():
    env = Envelope(
        schema_version=1,
        msg_id="x",
        ts=1.0,
        source_uid="a",
        kind=MessageKind.CHAT,
        payload={"text": f"{_DEFAULT_INSIGHT_PREFIX} some text"},
    )
    assert _is_ai_insight(env) is True


def test_is_ai_insight_false_pli():
    env = Envelope(
        schema_version=1,
        msg_id="x",
        ts=1.0,
        source_uid="a",
        kind=MessageKind.PLI,
        payload={"position": {"lat": 0, "lon": 0}},
    )
    assert _is_ai_insight(env) is False


def test_is_ai_insight_false_normal_chat():
    env = Envelope(
        schema_version=1,
        msg_id="x",
        ts=1.0,
        source_uid="a",
        kind=MessageKind.CHAT,
        payload={"text": "regular message"},
    )
    assert _is_ai_insight(env) is False


# ── _running lifecycle guard ────────────────────────────────────────────


async def test_inference_service_ignores_after_stop(mock_router, env):
    """After stop() is called, handle_message must not spawn tasks."""
    cfg = NemotronConfig(enabled=True, api_key="nvapi-test")
    svc = InferenceService(
        config=cfg,
        router=mock_router,
        clock=SystemClock(),
        id_factory=UuidFactory(),
        source_uid="node-base",
    )
    svc.start()
    await svc.stop()

    # Router still has the handler reference but service is stopped
    await mock_router.handlers[0](env)
    assert len(svc._bg_tasks) == 0


# ── double-start guard ──────────────────────────────────────────────────


async def test_inference_service_double_start_no_duplicate_subscribe(mock_router):
    cfg = NemotronConfig(enabled=True, api_key="nvapi-test")
    svc = InferenceService(
        config=cfg,
        router=mock_router,
        clock=SystemClock(),
        id_factory=UuidFactory(),
        source_uid="node-base",
    )
    svc.start()
    svc.start()  # second start must be idempotent
    assert len(mock_router.handlers) == 1


# ── missing API key logs warning and does not subscribe ─────────────────


async def test_inference_service_missing_api_key_does_not_start(mock_router):
    cfg = NemotronConfig(enabled=True, api_key="")
    svc = InferenceService(
        config=cfg,
        router=mock_router,
        clock=SystemClock(),
        id_factory=UuidFactory(),
        source_uid="node-base",
    )
    svc.start()
    assert len(mock_router.handlers) == 0
    assert svc._running is False


async def test_analyze_and_publish_empty_summary_noop(make_transport, mock_router, env):
    """When the API returns an empty summary, no message should be published."""
    cfg = NemotronConfig(enabled=True, api_key="nvapi-test")
    svc = InferenceService(
        config=cfg,
        router=mock_router,
        clock=SystemClock(),
        id_factory=UuidFactory(),
        source_uid="node-base",
        transport=make_transport([_ok("")]),
    )

    svc.start()
    await mock_router.handlers[0](env)

    for _ in range(200):
        if not svc._bg_tasks:
            break
        await asyncio.sleep(0)
    await svc.stop()

    assert len(mock_router.published) == 0


async def test_analyze_and_publish_exception_logged(make_transport, mock_router, env):
    """When the API call fails, the exception should be caught and logged."""
    cfg = NemotronConfig(enabled=True, api_key="nvapi-test", max_retries=0)
    svc = InferenceService(
        config=cfg,
        router=mock_router,
        clock=SystemClock(),
        id_factory=UuidFactory(),
        source_uid="node-base",
        transport=make_transport([InferenceTransportError("boom")]),
    )

    svc.start()
    await mock_router.handlers[0](env)

    for _ in range(200):
        if not svc._bg_tasks:
            break
        await asyncio.sleep(0)
    await svc.stop()

    # Exception was caught — no message published, no unhandled error
    assert len(mock_router.published) == 0


async def test_analyze_and_publish_propagates_cancellation(mock_router, env):
    """Cooperative cancellation must propagate, not be swallowed as a task failure."""

    class _CancellingTransport:
        async def post_json(self, url, *, headers, json_body, timeout_s):
            raise asyncio.CancelledError

        async def aclose(self) -> None:
            pass

    cfg = NemotronConfig(enabled=True, api_key="nvapi-test", max_retries=0)
    svc = InferenceService(
        config=cfg,
        router=mock_router,
        clock=SystemClock(),
        id_factory=UuidFactory(),
        source_uid="node-base",
        transport=_CancellingTransport(),
    )

    with pytest.raises(asyncio.CancelledError):
        await svc._analyze_and_publish(env)
    assert mock_router.published == []


# ── Track-B: rate limiting (concurrency + min-interval) ─────────────────


class _FixedClock:
    """A clock frozen at one instant, so elapsed-since-last is always zero."""

    def now(self) -> float:
        return 100.0


async def _await_published(mock_router, n: int) -> None:
    for _ in range(1000):
        if len(mock_router.published) >= n:
            return
        await asyncio.sleep(0)
    raise AssertionError(f"expected >= {n} published, got {len(mock_router.published)}")


async def _await_idle(svc) -> None:
    for _ in range(1000):
        if not svc._bg_tasks:
            return
        await asyncio.sleep(0)
    raise AssertionError(f"service never became idle: {len(svc._bg_tasks)} task(s) still running")


def _service(cfg, mock_router, transport, *, clock=None, sleep=None):
    kwargs = {}
    if sleep is not None:
        kwargs["sleep"] = sleep
    return InferenceService(
        config=cfg,
        router=mock_router,
        clock=clock or SystemClock(),
        id_factory=UuidFactory(),
        source_uid="node-base",
        transport=transport,
        **kwargs,
    )


async def test_service_min_interval_spaces_requests(make_transport, mock_router, env):
    """With a frozen clock, the second request waits min_interval_s; the first does not."""
    sleeps: list[float] = []

    async def rec_sleep(delay: float) -> None:
        sleeps.append(delay)

    cfg = NemotronConfig(enabled=True, api_key="k", min_interval_s=0.5)
    svc = _service(
        cfg, mock_router, make_transport([_ok("a"), _ok("b")]), clock=_FixedClock(), sleep=rec_sleep
    )
    svc.start()
    await mock_router.handlers[0](env)
    await mock_router.handlers[0](env)
    await _await_published(mock_router, 2)
    await svc.stop()

    assert len(mock_router.published) == 2
    assert sleeps == [pytest.approx(0.5)]  # exactly one spacing wait, for the 2nd request


async def test_service_min_interval_no_wait_when_elapsed_exceeds(
    make_transport, mock_router, env, clock
):
    """When more than min_interval_s has elapsed, no spacing wait occurs (wait<=0 branch)."""
    sleeps: list[float] = []

    async def rec_sleep(delay: float) -> None:
        sleeps.append(delay)

    # The conftest FakeClock (via the `clock` fixture) advances 1.0s per now() call — always
    # > 0.5s of spacing.
    cfg = NemotronConfig(enabled=True, api_key="k", min_interval_s=0.5)
    svc = _service(
        cfg, mock_router, make_transport([_ok("a"), _ok("b")]), clock=clock, sleep=rec_sleep
    )
    svc.start()
    await mock_router.handlers[0](env)
    await _await_idle(svc)
    await mock_router.handlers[0](env)
    await _await_published(mock_router, 2)
    await svc.stop()

    assert sleeps == []  # clock advanced past the interval — never waited


def test_service_bounded_semaphore_created_when_configured(mock_router, make_transport):
    cfg = NemotronConfig(enabled=True, api_key="k", max_concurrent_requests=2)
    svc = _service(cfg, mock_router, make_transport([]))
    assert isinstance(svc._rate_gate._semaphore, asyncio.BoundedSemaphore)


def test_service_no_semaphore_by_default(mock_router, make_transport):
    cfg = NemotronConfig(enabled=True, api_key="k")
    svc = _service(cfg, mock_router, make_transport([]))
    assert svc._rate_gate._semaphore is None


async def test_service_publishes_under_concurrency_limit(make_transport, mock_router, env):
    """Two messages both publish while gated by a max_concurrent_requests=1 semaphore."""
    cfg = NemotronConfig(enabled=True, api_key="k", max_concurrent_requests=1)
    svc = _service(cfg, mock_router, make_transport([_ok("a"), _ok("b")]))
    svc.start()
    await mock_router.handlers[0](env)
    await mock_router.handlers[0](env)
    await _await_published(mock_router, 2)
    await svc.stop()
    assert len(mock_router.published) == 2


# ── Track-B: offline queue (enqueue-on-failure, replay-on-recovery) ─────


async def test_service_offline_queue_replays_on_recovery(make_transport, mock_router, env):
    """A failed analysis is queued, then replayed and published on the next success."""
    cfg = NemotronConfig(enabled=True, api_key="k", max_retries=0, offline_queue_max=4)
    # msg1 fails; msg2 succeeds (publishes s2) then drains msg1 (publishes s1-replay).
    transport = make_transport([InferenceTransportError("down"), _ok("s2"), _ok("s1-replay")])
    svc = _service(cfg, mock_router, transport)
    svc.start()

    await mock_router.handlers[0](env)  # message 1 -> fails -> queued
    await _await_idle(svc)
    assert svc._offline_queue._queue is not None and len(svc._offline_queue._queue) == 1

    await mock_router.handlers[0](env)  # message 2 -> success -> publish + drain replay
    await _await_published(mock_router, 2)
    await svc.stop()

    assert len(mock_router.published) == 2
    assert not svc._offline_queue  # queue drained


async def test_service_offline_queue_drops_oldest_when_full(make_transport, mock_router, env):
    """Overflow drops the oldest and increments the drop counter (drop-and-count)."""
    cfg = NemotronConfig(enabled=True, api_key="k", max_retries=0, offline_queue_max=1)
    transport = make_transport([InferenceTransportError("x")], repeat_last=True)
    svc = _service(cfg, mock_router, transport)
    svc.start()

    await mock_router.handlers[0](env)
    await _await_idle(svc)
    await mock_router.handlers[0](env)
    await _await_idle(svc)
    await svc.stop()

    assert svc._offline_queue._queue is not None and len(svc._offline_queue._queue) == 1
    assert svc._offline_queue._dropped == 1


async def test_service_offline_replay_requeues_on_repeat_failure(make_transport, mock_router, env):
    """If a replay fails again, the envelope is re-queued and draining stops."""
    cfg = NemotronConfig(enabled=True, api_key="k", max_retries=0, offline_queue_max=4)
    # msg1 fails -> queued; msg2 ok -> publish; drain replays msg1 -> fails -> re-queued.
    transport = make_transport(
        [InferenceTransportError("a"), _ok("s2"), InferenceTransportError("b")]
    )
    svc = _service(cfg, mock_router, transport)
    svc.start()

    await mock_router.handlers[0](env)
    await _await_idle(svc)
    await mock_router.handlers[0](env)
    await _await_published(mock_router, 1)
    await svc.stop()

    assert len(mock_router.published) == 1  # only s2
    assert (
        svc._offline_queue._queue is not None and len(svc._offline_queue._queue) == 1
    )  # msg1 back


async def test_service_offline_replay_skips_empty_summary(make_transport, mock_router, env):
    """A replay that yields an empty summary is not published (drain's summary guard)."""
    cfg = NemotronConfig(enabled=True, api_key="k", max_retries=0, offline_queue_max=4)
    # msg1 fails -> queued; msg2 ok -> publish; drain replays msg1 -> empty content -> no publish.
    transport = make_transport([InferenceTransportError("a"), _ok("s2"), _ok("")])
    svc = _service(cfg, mock_router, transport)
    svc.start()

    await mock_router.handlers[0](env)
    await _await_idle(svc)
    await mock_router.handlers[0](env)
    await _await_published(mock_router, 1)
    await _await_idle(svc)
    await svc.stop()

    assert len(mock_router.published) == 1  # only s2; the empty replay is dropped
    assert not svc._offline_queue


def _pli(msg_id: str, source_uid: str) -> Envelope:
    return Envelope(
        schema_version=1,
        msg_id=msg_id,
        ts=1.0,
        source_uid=source_uid,
        kind=MessageKind.PLI,
        payload={"position": {"lat": 1.0, "lon": 2.0}},
    )


async def test_service_offline_replay_failure_preserves_fifo_order(make_transport, mock_router):
    """A failed replay returns to the FRONT of the queue, ahead of newer entries (FIFO)."""
    cfg = NemotronConfig(enabled=True, api_key="k", max_retries=0, offline_queue_max=4)
    a, b, c = _pli("a", "u1"), _pli("b", "u2"), _pli("c", "u3")
    # a fails -> [a]; b fails -> [a, b]; c ok -> publish, drain pops a -> fails -> back to front.
    transport = make_transport(
        [
            InferenceTransportError("a"),
            InferenceTransportError("b"),
            _ok("c-ok"),
            InferenceTransportError("a2"),
        ]
    )
    svc = _service(cfg, mock_router, transport)
    svc.start()

    await mock_router.handlers[0](a)
    await _await_idle(svc)
    await mock_router.handlers[0](b)
    await _await_idle(svc)
    await mock_router.handlers[0](c)
    await _await_published(mock_router, 1)
    await _await_idle(svc)
    await svc.stop()

    assert len(mock_router.published) == 1  # only c
    assert svc._offline_queue._queue is not None
    # 'a' stayed at the front (appendleft), 'b' still behind it — arrival order preserved.
    assert [e.msg_id for e in svc._offline_queue._queue] == ["a", "b"]


# ── Track-B hardening: offline error classification + gated drain ───────


async def test_service_permanent_http_error_not_queued(make_transport, mock_router, env):
    """A permanent 4xx (401 bad key) must NOT be queued for offline replay."""
    cfg = NemotronConfig(enabled=True, api_key="bad", max_retries=0, offline_queue_max=4)
    svc = _service(cfg, mock_router, make_transport([HttpResponse(status=401, payload={})]))
    svc.start()
    await mock_router.handlers[0](env)
    await _await_idle(svc)
    await svc.stop()
    assert mock_router.published == []
    assert (
        svc._offline_queue._queue is not None and len(svc._offline_queue._queue) == 0
    )  # fails fast


async def test_service_malformed_payload_not_queued(make_transport, mock_router, env):
    """A malformed 200 body (base InferenceError) must NOT be queued (never replays clean)."""
    cfg = NemotronConfig(enabled=True, api_key="k", max_retries=0, offline_queue_max=4)
    svc = _service(cfg, mock_router, make_transport([HttpResponse(status=200, payload={"x": 1})]))
    svc.start()
    await mock_router.handlers[0](env)
    await _await_idle(svc)
    await svc.stop()
    assert mock_router.published == []
    assert svc._offline_queue._queue is not None and len(svc._offline_queue._queue) == 0


async def test_service_5xx_exhausted_is_queued(make_transport, mock_router, env):
    """A 5xx that survives retries IS transient → queued for offline replay."""
    cfg = NemotronConfig(enabled=True, api_key="k", max_retries=0, offline_queue_max=4)
    svc = _service(cfg, mock_router, make_transport([HttpResponse(status=503, payload={})]))
    svc.start()
    await mock_router.handlers[0](env)
    await _await_idle(svc)
    await svc.stop()
    assert svc._offline_queue._queue is not None and len(svc._offline_queue._queue) == 1


async def test_service_drain_honors_min_interval(make_transport, mock_router, env):
    """Offline replay goes through the same rate gate as live requests (no burst)."""
    sleeps: list[float] = []

    async def rec_sleep(delay: float) -> None:
        sleeps.append(delay)

    cfg = NemotronConfig(
        enabled=True, api_key="k", max_retries=0, offline_queue_max=4, min_interval_s=0.5
    )
    # msg1 fails (transient) -> queued; msg2 ok -> publish + drain replays msg1 ok.
    transport = make_transport([InferenceTransportError("down"), _ok("s2"), _ok("s1")])
    svc = _service(cfg, mock_router, transport, clock=_FixedClock(), sleep=rec_sleep)
    svc.start()
    await mock_router.handlers[0](env)
    await _await_idle(svc)
    await mock_router.handlers[0](env)
    await _await_published(mock_router, 2)
    await svc.stop()
    # 3 gated calls total (fail, live-ok, replay-ok); the 2nd and 3rd each wait one interval.
    assert sleeps == [pytest.approx(0.5), pytest.approx(0.5)]


async def test_service_drain_drops_permanent_and_continues(make_transport, mock_router):
    """A replay failing permanently is dropped (counted) and draining continues to the next."""
    a, b, c = _pli("a", "u1"), _pli("b", "u2"), _pli("c", "u3")
    cfg = NemotronConfig(enabled=True, api_key="k", max_retries=0, offline_queue_max=4)
    # a,b fail (transient) -> [a, b]; c ok -> publish; drain: a -> 401 permanent (drop+continue),
    # b -> ok (publish).
    transport = make_transport(
        [
            InferenceTransportError("a"),
            InferenceTransportError("b"),
            _ok("c-ok"),
            HttpResponse(status=401, payload={}),
            _ok("b-replay"),
        ]
    )
    svc = _service(cfg, mock_router, transport)
    svc.start()
    await mock_router.handlers[0](a)
    await _await_idle(svc)
    await mock_router.handlers[0](b)
    await _await_idle(svc)
    await mock_router.handlers[0](c)
    await _await_published(mock_router, 2)
    await _await_idle(svc)
    await svc.stop()

    assert len(mock_router.published) == 2  # c-ok + b-replay; 'a' was dropped as permanent
    assert svc._offline_queue._queue is not None and len(svc._offline_queue._queue) == 0
    assert svc._offline_queue._dropped == 1


async def test_service_non_inference_exception_logged_not_queued(make_transport, mock_router, env):
    """A non-InferenceError (e.g. an unexpected bug) is caught + logged, never queued or raised."""
    cfg = NemotronConfig(enabled=True, api_key="k", max_retries=0, offline_queue_max=4)
    # A plain RuntimeError from the transport is not an InferenceError — it bypasses the retry
    # loop and the offline classifier, hitting the task-level safety net.
    svc = _service(cfg, mock_router, make_transport([RuntimeError("unexpected bug")]))
    svc.start()
    await mock_router.handlers[0](env)
    await _await_idle(svc)
    await svc.stop()
    assert mock_router.published == []
    assert (
        svc._offline_queue._queue is not None and len(svc._offline_queue._queue) == 0
    )  # not queued


# ── Backpressure: bound handle_message task intake (max_pending_tasks) ──────


def _chat_envelope(text: str, *, source_uid: str) -> Envelope:
    return Envelope(
        schema_version=1,
        msg_id="chat-1",
        ts=1.0,
        source_uid=source_uid,
        kind=MessageKind.CHAT,
        payload={"text": text},
    )


async def test_handle_message_sheds_when_pending_tasks_at_cap(make_transport, mock_router):
    # With the cap reached, a new inbound envelope is dropped-and-counted, no task spawned.
    cfg = NemotronConfig(enabled=True, api_key="k", max_pending_tasks=1)
    svc = _service(cfg, mock_router, make_transport([]))
    svc._running = True
    # Simulate one in-flight task already occupying the only slot.
    slow = asyncio.get_event_loop().create_future()
    svc._bg_tasks.add(asyncio.ensure_future(slow))
    await svc.handle_message(_chat_envelope("hello", source_uid="other"))
    assert svc._intake_dropped == 1
    assert len(svc._bg_tasks) == 1  # no new task added
    slow.set_result(None)
    await svc.stop()  # tear down the service so no in-flight state leaks into later tests


async def test_handle_message_accepts_below_cap_then_sheds_at_cap(make_transport, mock_router):
    # cap=3 (not the degenerate cap=1 case): below cap must accept and spawn a task;
    # only once occupancy reaches the cap does intake shed.
    cfg = NemotronConfig(enabled=True, api_key="k", max_pending_tasks=3)
    svc = _service(cfg, mock_router, make_transport([]))
    svc._running = True

    # Occupy 2 of 3 slots with fake in-flight tasks (mirrors the cap=1 shed test's technique).
    slow1 = asyncio.get_event_loop().create_future()
    slow2 = asyncio.get_event_loop().create_future()
    svc._bg_tasks.add(asyncio.ensure_future(slow1))
    svc._bg_tasks.add(asyncio.ensure_future(slow2))

    # len(_bg_tasks)==2 < cap==3: the envelope must be accepted (a new task scheduled),
    # not shed — the accept-path signal, mirrored by the dropped counter staying put.
    await svc.handle_message(_chat_envelope("hello", source_uid="other"))
    assert svc._intake_dropped == 0
    assert len(svc._bg_tasks) == 3  # 2 fakes + 1 newly-spawned real task

    # Occupy the 3rd slot with a fake too, so occupancy is deterministically pinned at the
    # cap (3) rather than depending on the real task above ever completing.
    slow3 = asyncio.get_event_loop().create_future()
    svc._bg_tasks.add(asyncio.ensure_future(slow3))
    assert len(svc._bg_tasks) == 4  # 3 fakes + 1 real, all still in-flight

    # len(_bg_tasks)==4 >= cap==3: the next envelope must now be shed.
    await svc.handle_message(_chat_envelope("world", source_uid="other"))
    assert svc._intake_dropped == 1
    assert len(svc._bg_tasks) == 4  # no new task added

    slow1.set_result(None)
    slow2.set_result(None)
    slow3.set_result(None)
    # The below-cap accept above spawned a real _analyze_and_publish task; stop the service so it
    # is cancelled here rather than running later and emitting unrelated log noise into other tests.
    await svc.stop()


async def test_handle_message_unbounded_when_cap_zero(make_transport, mock_router):
    cfg = NemotronConfig(enabled=True, api_key="k", max_pending_tasks=0)
    svc = _service(cfg, mock_router, make_transport([_ok("hi-reply")]))
    svc._running = True
    await svc.handle_message(_chat_envelope("hi", source_uid="other"))
    assert svc._intake_dropped == 0
    await _await_published(mock_router, 1)
    await svc.stop()


# ── InferenceService.as_dict(): point-in-time counters accessor ─────────────


def test_as_dict_reports_counters(mock_router, make_transport):
    cfg = NemotronConfig(enabled=True, api_key="k", offline_queue_max=4, max_pending_tasks=2)
    svc = _service(cfg, mock_router, make_transport([]))
    svc._offline_queue._dropped = 3
    svc._intake_dropped = 5
    assert svc._offline_queue._queue is not None
    svc._offline_queue._queue.append(_chat_envelope("q", source_uid="x"))  # depth 1
    d = svc.as_dict()
    assert d == {
        "offline_dropped": 3,
        "offline_queue_depth": 1,
        "intake_dropped": 5,
        "pending_tasks": 0,
    }


def test_as_dict_zero_depth_when_offline_disabled(mock_router, make_transport):
    cfg = NemotronConfig(enabled=True, api_key="k", offline_queue_max=0)
    svc = _service(cfg, mock_router, make_transport([]))
    assert svc.as_dict()["offline_queue_depth"] == 0
