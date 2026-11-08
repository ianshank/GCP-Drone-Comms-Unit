"""Direct tests for ``meshsa._queues`` (T-3.5b): the shared drop accounting and the deque queue.

The transport inbox and the inference offline queue exercise these through their own
suites; this file pins the primitives' contract so a change to one adopter cannot
silently change the other's drop semantics.
"""

from __future__ import annotations

import pytest

from meshsa._queues import BoundedDropQueue, DropCounter


class _Log:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def warning(self, event: str, **fields: object) -> None:
        self.calls.append((event, fields))


# ---- DropCounter -------------------------------------------------------------


def test_counter_warns_on_first_drop_and_every_nth() -> None:
    log = _Log()
    counter = DropCounter(log, "dropped", log_every=3, transport="t")
    assert [counter.record() for _ in range(7)] == [1, 2, 3, 4, 5, 6, 7]
    assert counter.count == 7
    assert [fields["dropped"] for _, fields in log.calls] == [1, 3, 6]
    assert all(event == "dropped" and fields["transport"] == "t" for event, fields in log.calls)


def test_counter_default_logs_every_drop_under_a_custom_field() -> None:
    log = _Log()
    counter = DropCounter(log, "inbox_full", counter_field="dropped_inbox_full")
    counter.record()
    counter.record(reason="x")
    assert log.calls == [
        ("inbox_full", {"dropped_inbox_full": 1}),
        ("inbox_full", {"reason": "x", "dropped_inbox_full": 2}),
    ]


def test_counter_quiet_counts_without_a_warning() -> None:
    log = _Log()
    counter = DropCounter(log, "dropped")
    assert counter.record(quiet=True) == 1
    assert counter.count == 1
    assert log.calls == []


def test_counter_rejects_a_zero_interval() -> None:
    with pytest.raises(ValueError, match="log_every must be >= 1"):
        DropCounter(_Log(), "dropped", log_every=0)


# ---- BoundedDropQueue --------------------------------------------------------


def _queue(policy: str, maxlen: int = 2) -> tuple[BoundedDropQueue[str], _Log]:
    log = _Log()
    q: BoundedDropQueue[str] = BoundedDropQueue(
        maxlen,
        DropCounter(log, "dropped"),
        policy=policy,  # type: ignore[arg-type]
    )
    return q, log


def test_queue_is_fifo_and_reports_its_bound() -> None:
    q, _ = _queue("newest")
    assert q.maxlen == 2
    assert not q and len(q) == 0
    assert q.put("a") and q.put("b")
    assert q and list(q) == ["a", "b"]
    assert q.pop() == "a"
    assert q.pop() == "b"
    assert not q


def test_newest_policy_refuses_the_arriving_item_and_counts_it() -> None:
    q, log = _queue("newest")
    q.put("a")
    q.put("b")
    assert q.put("c") is False
    assert list(q) == ["a", "b"]
    assert q.dropped == 1 and q.counter.count == 1
    assert [fields["dropped"] for _, fields in log.calls] == [1]


def test_oldest_policy_evicts_the_head_and_keeps_the_arriving_item() -> None:
    q, _ = _queue("oldest")
    q.put("a")
    q.put("b")
    assert q.put("c") is True
    assert list(q) == ["b", "c"]
    assert q.dropped == 1


def test_front_put_requeues_at_the_head() -> None:
    q, _ = _queue("oldest", maxlen=3)
    q.put("b")
    assert q.put("a", front=True) is True
    assert list(q) == ["a", "b"]


def test_front_put_on_a_full_oldest_queue_evicts_the_tail() -> None:
    """A requeued head must not evict itself: the opposite end gives way."""
    q, _ = _queue("oldest")
    q.put("b")
    q.put("c")
    assert q.put("a", front=True) is True
    assert list(q) == ["a", "b"]
    assert q.dropped == 1


def test_front_put_on_a_full_newest_queue_is_refused() -> None:
    q, _ = _queue("newest")
    q.put("b")
    q.put("c")
    assert q.put("a", front=True) is False
    assert list(q) == ["b", "c"]


def test_queue_rejects_a_zero_bound() -> None:
    with pytest.raises(ValueError, match="maxlen must be >= 1"):
        BoundedDropQueue(0, DropCounter(_Log(), "dropped"))


def test_counter_fields_that_repeat_a_bound_name_do_not_raise() -> None:
    """The drop path must never raise: a repeated key is resolved, later value winning."""
    log = _Log()
    counter = DropCounter(log, "dropped", transport="a")
    assert counter.record(transport="b", dropped=99) == 1
    assert log.calls == [("dropped", {"transport": "b", "dropped": 1})]
