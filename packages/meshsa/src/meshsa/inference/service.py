"""``InferenceService``: subscribes to mesh traffic, runs inference, broadcasts insights.

Split out of the former flat ``inference.py`` (code-hygiene-modularity T-4.1b).
``_RateGate``/``_OfflineQueue`` were extracted from ``InferenceService`` itself
in an earlier step of the same task (T-4.1a).
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable

import structlog

from ..models import ChatPayload, Envelope, MessageKind
from ..protocols import Clock, IdFactory
from ..router import Router
from ..version import SCHEMA_VERSION
from .client import InferenceResult, NemotronClient
from .config import NemotronConfig
from .errors import InferenceError, _is_offline_retryable
from .transport import HttpTransport

_log = structlog.get_logger("meshsa.inference")

# Default prefix applied to all AI-generated messages. Used by
# ``_is_ai_insight`` to prevent multi-node feedback loops.
_DEFAULT_INSIGHT_PREFIX = "[AI Insight]"


def _is_ai_insight(envelope: Envelope, prefix: str = _DEFAULT_INSIGHT_PREFIX) -> bool:
    """Return True when the envelope is an AI-generated insight message."""
    if envelope.kind != MessageKind.CHAT:
        return False
    text: str = envelope.payload.get("text", "") if isinstance(envelope.payload, dict) else ""
    return text.startswith(prefix)


class _RateGate:
    """Bounds InferenceService's outbound request concurrency and rate.

    Extracted from InferenceService (code-hygiene-modularity T-4.1a). A
    ``BoundedSemaphore`` caps *concurrency*; the min-interval spacing caps *rate* —
    a semaphore alone cannot. Both are no-ops at their configured defaults (0),
    preserving prior service behavior.
    """

    def __init__(
        self,
        *,
        max_concurrent_requests: int,
        min_interval_s: float,
        clock: Clock,
        sleep: Callable[[float], Awaitable[None]],
    ) -> None:
        self._semaphore: asyncio.BoundedSemaphore | None = (
            asyncio.BoundedSemaphore(max_concurrent_requests)
            if max_concurrent_requests > 0
            else None
        )
        self._min_interval_s = min_interval_s
        self._clock = clock
        self._sleep = sleep
        self._interval_lock = asyncio.Lock()
        self._last_request_at: float | None = None

    async def _space(self) -> None:
        """Enforce ``min_interval_s`` spacing between requests via the injected clock."""
        if self._min_interval_s <= 0:
            return
        async with self._interval_lock:
            now = self._clock.now()
            if self._last_request_at is not None:
                wait = self._min_interval_s - (now - self._last_request_at)
                if wait > 0:
                    await self._sleep(wait)
            self._last_request_at = self._clock.now()

    async def run(self, call: Callable[[], Awaitable[InferenceResult]]) -> InferenceResult:
        """Space, then run ``call`` under the concurrency permit (if any).

        Spacing happens *before* acquiring a permit (so a permit is never spent merely
        waiting). The permit then wraps the whole call — **including its internal
        retry/backoff sleeps** — so under transient failures a slot is held across
        retries. That is deliberate: ``max_concurrent_requests`` bounds in-flight
        requests *inclusive of retries* to cap edge API spend (spec §5). Both live
        requests and each offline replay go through this same gate, so they honor
        ``min_interval_s``/``max_concurrent_requests`` identically.
        """
        await self._space()
        if self._semaphore is None:
            return await call()
        async with self._semaphore:
            return await call()


class _OfflineQueue:
    """Bounded queue of envelopes that failed while the API was unreachable.

    Extracted from InferenceService (code-hygiene-modularity T-4.1a). A failure
    (transport/HTTP error surviving retries) enqueues the envelope (drop-and-count
    on overflow, mirroring ``FlightLogger``); the next success drains/replays it.
    ``maxlen=0`` disables queueing entirely, preserving prior service behavior.
    """

    def __init__(self, maxlen: int) -> None:
        self._queue: deque[Envelope] | None = deque(maxlen=maxlen) if maxlen > 0 else None
        self._dropped = 0
        self.drain_lock = asyncio.Lock()

    def __bool__(self) -> bool:
        """True when the queue currently holds items (mirrors the prior ``self._offline``
        truthiness check — distinct from :attr:`enabled`, which is true even when empty)."""
        return bool(self._queue)

    @property
    def enabled(self) -> bool:
        """True when queueing is configured at all (``maxlen > 0``), even if currently
        empty — the check a fresh failure needs before its first enqueue."""
        return self._queue is not None

    @property
    def dropped(self) -> int:
        return self._dropped

    @property
    def depth(self) -> int:
        return len(self._queue) if self._queue is not None else 0

    def put(self, envelope: Envelope, *, front: bool) -> None:
        """Add ``envelope`` to either end, counting any overflow.

        Callers only reach here after an :attr:`enabled`/truthiness check, so
        ``self._queue`` is always a real deque (never called while disabled).

        ``front=True`` (a re-queued replay) preserves FIFO — the item returns to where
        it was popped. A full deque silently drops the item at the opposite end on
        insert, so we count it (drop-and-count) rather than lose it silently — this
        also covers the case where a concurrent producer refilled the queue during a
        drain ``await``.
        """
        assert self._queue is not None
        if len(self._queue) == self._queue.maxlen:
            self._dropped += 1
            _log.warning("inference_offline_dropped", dropped_total=self._dropped)
        if front:
            self._queue.appendleft(envelope)
        else:
            self._queue.append(envelope)

    def pop(self) -> Envelope:
        assert self._queue is not None  # callers only pop after a truthiness check
        return self._queue.popleft()

    def record_drop(self) -> None:
        """Count a drop that happens outside :meth:`put` (a permanently-failed replay)."""
        self._dropped += 1


class InferenceService:
    """Subscribes to mesh traffic, runs inference, and broadcasts insights."""

    def __init__(
        self,
        config: NemotronConfig,
        router: Router,
        clock: Clock,
        id_factory: IdFactory,
        source_uid: str,
        *,
        transport: HttpTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.config = config
        self.router = router
        self.clock = clock
        self.id_factory = id_factory
        self.source_uid = source_uid
        self.client = NemotronClient(config, transport=transport, sleep=sleep)
        self._sleep = sleep
        self._bg_tasks: set[asyncio.Task[None]] = set()
        self._running = False
        self._subscribed = False
        # ── Rate limiting (spec §5): _RateGate bounds concurrency + min-interval rate. ──
        self._rate_gate = _RateGate(
            max_concurrent_requests=config.max_concurrent_requests,
            min_interval_s=config.min_interval_s,
            clock=clock,
            sleep=sleep,
        )
        # ── Offline fallback (spec §5): _OfflineQueue holds envelopes that failed while
        #    the API was unreachable, replayed on the next success. ──
        self._offline_queue = _OfflineQueue(config.offline_queue_max)
        self._intake_dropped = 0

    def start(self) -> None:
        if not self.config.enabled or self._subscribed:
            return
        if not self.config.api_key:
            _log.warning("inference_service_missing_api_key")
            return
        self._subscribed = True
        self._running = True
        self.router.subscribe(self.handle_message)
        _log.info("inference_service_started", model=self.config.model)

    async def handle_message(self, envelope: Envelope) -> None:
        # Bail if the service has been stopped.
        if not self._running:
            return

        # Prevent infinite loops by not responding to our own inference messages.
        if envelope.source_uid == self.source_uid:
            return

        # Avoid analyzing existing AI insights to prevent multi-node feedback loops.
        if _is_ai_insight(envelope, self.config.insight_prefix):
            return

        # Backpressure: shed (drop-and-count) rather than spawn unbounded tasks on a
        # constrained edge node once in-flight analysis tasks reach the configured cap.
        # 0 (the default) preserves prior, unbounded behavior.
        cap = self.config.max_pending_tasks
        if cap and len(self._bg_tasks) >= cap:
            self._intake_dropped += 1
            _log.warning(
                "inference_intake_dropped",
                dropped_total=self._intake_dropped,
                pending=len(self._bg_tasks),
                cap=cap,
            )
            return

        task = asyncio.create_task(self._analyze_and_publish(envelope))
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    async def _analyze_and_publish(self, envelope: Envelope) -> None:
        try:
            result = await self._gated_analyze(envelope)
            if not result.summary:
                return
            await self._publish(envelope, result)
            # Drain OUTSIDE any semaphore permit (`_gated_analyze` already released it) so a
            # backlog flush doesn't monopolize the concurrency cap.
            await self._drain_offline()
        except asyncio.CancelledError:
            raise
        except InferenceError as exc:
            # A connectivity/transient failure is queued for later replay (when a queue is
            # configured); a permanent one (bad key, malformed body) surfaces as before so it
            # fails fast and loud instead of cycling in the queue forever.
            if self._offline_queue.enabled and _is_offline_retryable(exc):
                self._offline_queue.put(envelope, front=False)
                _log.warning(
                    "inference_offline_enqueue", original_id=envelope.msg_id, error=str(exc)
                )
            else:
                _log.warning("inference_task_failed", exc_info=True)
        except Exception:
            _log.warning("inference_task_failed", exc_info=True)

    async def _gated_analyze(self, envelope: Envelope) -> InferenceResult:
        """Run one analysis through the rate-limit gate (see :class:`_RateGate`).

        Both live requests and each offline replay call this same method, so they
        honor ``min_interval_s``/``max_concurrent_requests`` identically.
        """
        return await self._rate_gate.run(lambda: self.client.analyze(envelope))

    async def _publish(self, envelope: Envelope, result: InferenceResult) -> None:
        reply = Envelope(
            schema_version=SCHEMA_VERSION,
            msg_id=self.id_factory.new_id(),
            ts=self.clock.now(),
            source_uid=self.source_uid,
            kind=MessageKind.CHAT,
            payload=ChatPayload(
                text=f"{self.config.insight_prefix} {result.summary}",
                to=envelope.source_uid,
            ).model_dump(),
        )
        await self.router.publish(reply)
        _log.info("inference_published", original_id=envelope.msg_id, reply_id=reply.msg_id)

    async def _drain_offline(self) -> None:
        """Replay queued envelopes after a success.

        A *transient* replay failure returns the item to the FRONT (FIFO) and stops draining —
        connectivity is likely down again. A *permanent* replay failure drops the item (counted)
        and continues, so one poison envelope can never block replay of the rest.
        """
        if not self._offline_queue:
            return
        async with self._offline_queue.drain_lock:
            while self._offline_queue:
                pending = self._offline_queue.pop()
                try:
                    result = await self._gated_analyze(pending)
                except InferenceError as exc:
                    if _is_offline_retryable(exc):
                        self._offline_queue.put(pending, front=True)
                        _log.warning("inference_offline_replay_failed", error=str(exc))
                        return
                    self._offline_queue.record_drop()
                    _log.warning(
                        "inference_offline_replay_dropped",
                        dropped_total=self._offline_queue.dropped,
                        error=str(exc),
                    )
                    continue
                if result.summary:
                    await self._publish(pending, result)

    async def stop(self) -> None:
        self._running = False
        for t in list(self._bg_tasks):
            t.cancel()
        if self._bg_tasks:
            await asyncio.gather(*self._bg_tasks, return_exceptions=True)
        self._bg_tasks.clear()
        await self.client.close()

    def as_dict(self) -> dict[str, int]:
        """Point-in-time service counters for the ``/metrics`` exporter (pure read).

        Mirrors the transport counter-attribute convention consumed by
        :func:`meshsa.health._transport_counters`. ``offline_dropped`` /
        ``intake_dropped`` are monotonic counters; ``offline_queue_depth`` /
        ``pending_tasks`` are instantaneous gauges.
        """
        return {
            "offline_dropped": self._offline_queue.dropped,
            "offline_queue_depth": self._offline_queue.depth,
            "intake_dropped": self._intake_dropped,
            "pending_tasks": len(self._bg_tasks),
        }
