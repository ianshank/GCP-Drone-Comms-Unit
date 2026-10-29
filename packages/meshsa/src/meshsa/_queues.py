"""Drop-and-count primitives shared by the bounded queues (code-hygiene-modularity T-3.5b).

Three places bound a producer against a slow consumer and count what they drop: the
transport inbox (an ``asyncio.Queue`` the router awaits), the inference offline queue (a
``deque`` replayed on the next success) and the flight logger's writer queue (a
``queue.Queue`` drained by a thread). The *queues* stay what they are — each backend is
the right one for its concurrency model, and re-implementing blocking or async semantics
to share a class would be risk for aesthetics. What they share is the **accounting**:
a monotonic drop counter and a warning on the first drop and every Nth after, so a stuck
consumer is visible without a log line per frame. :class:`DropCounter` is that one
implementation; :class:`BoundedDropQueue` is the synchronous deque-backed queue with the
counter built in, for the sites that need no cross-thread or async handoff.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterator
from typing import Any, Generic, Literal, TypeVar

__all__ = ["BoundedDropQueue", "DropCounter", "DropPolicy"]

T = TypeVar("T")

#: Which end gives way when the queue is full. ``"newest"`` refuses the arriving item (a
#: frame already accepted for in-order delivery is never discarded); ``"oldest"`` evicts
#: the head so the most recent item is kept (a replay queue wants the latest state).
DropPolicy = Literal["newest", "oldest"]


class DropCounter:
    """A monotonic drop counter with a throttled warning: the 1st drop, then every Nth.

    ``log`` is any structlog-style logger (``warning(event, **fields)``); ``fields`` given at
    construction are attached to every warning (``transport=name``), and the current count
    is always attached under ``counter_field``.
    """

    def __init__(
        self,
        log: Any,
        event: str,
        *,
        log_every: int = 1,
        counter_field: str = "dropped",
        **fields: object,
    ) -> None:
        if log_every < 1:
            raise ValueError(f"log_every must be >= 1, got {log_every}")
        self._log = log
        self._event = event
        self._log_every = log_every
        self._counter_field = counter_field
        self._fields = fields
        self.count = 0

    def record(self, *, quiet: bool = False, **fields: object) -> int:
        """Count one drop; warn on the first and every ``log_every``th. Returns the count.

        ``quiet=True`` counts without the warning, for a drop the caller has already
        logged in its own terms (a permanently failed replay).
        """
        self.count += 1
        if not quiet and (self.count == 1 or self.count % self._log_every == 0):
            self._log.warning(
                self._event, **self._fields, **fields, **{self._counter_field: self.count}
            )
        return self.count


class BoundedDropQueue(Generic[T]):
    """A bounded synchronous queue that drops-and-counts instead of blocking or raising.

    ``maxlen`` is the bound (``> 0``); ``policy`` says which end gives way (see
    :data:`DropPolicy`). :meth:`put` returns whether the *arriving* item was kept, so a
    caller can tell a refused item from an evicted one.
    """

    def __init__(self, maxlen: int, counter: DropCounter, *, policy: DropPolicy = "newest") -> None:
        if maxlen < 1:
            raise ValueError(f"maxlen must be >= 1, got {maxlen}")
        self._items: deque[T] = deque()
        self._maxlen = maxlen
        self._policy: DropPolicy = policy
        self.counter = counter

    @property
    def maxlen(self) -> int:
        return self._maxlen

    @property
    def dropped(self) -> int:
        """Items dropped so far (the counter's count)."""
        return self.counter.count

    def __len__(self) -> int:
        return len(self._items)

    def __bool__(self) -> bool:
        return bool(self._items)

    def __iter__(self) -> Iterator[T]:
        return iter(self._items)

    def put(self, item: T, *, front: bool = False) -> bool:
        """Add ``item`` (at the tail, or the head with ``front=True``); return whether it was kept.

        When full: ``"newest"`` refuses ``item`` and counts it; ``"oldest"`` evicts the item
        at the opposite end from where ``item`` goes, counts that, and keeps ``item``.
        """
        if len(self._items) >= self._maxlen:
            self.counter.record()
            if self._policy == "newest":
                return False
            if front:
                self._items.pop()
            else:
                self._items.popleft()
        if front:
            self._items.appendleft(item)
        else:
            self._items.append(item)
        return True

    def pop(self) -> T:
        """Remove and return the head (FIFO)."""
        return self._items.popleft()
