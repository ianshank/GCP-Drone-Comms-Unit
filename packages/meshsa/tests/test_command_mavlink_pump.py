"""MavlinkCommandPump fan-out + lifecycle (fakes-only; injected fake connection)."""

import threading

import pytest

from meshsa.command import Ack, MavlinkCommandPump


class FakeLink:
    """Stands in for MavlinkCommandLink: records start/send/close, packs nothing."""

    def __init__(self) -> None:
        self.started = False
        self.closed = False
        self.sent: list[object] = []

    def start(self) -> None:
        self.started = True

    def send(self, spec: object) -> None:
        self.sent.append(spec)

    def close(self) -> None:
        self.closed = True


class FakeMsg:
    def __init__(self, mtype, *, sys=1, comp=1, command=0, result=0) -> None:
        self._type = mtype
        self._sys = sys
        self._comp = comp
        self.command = command
        self.result = result

    def get_type(self) -> str:
        return self._type

    def get_srcSystem(self) -> int:
        return self._sys

    def get_srcComponent(self) -> int:
        return self._comp


class ScriptedConn:
    """Yields a queued sequence of messages from recv_match, then None forever."""

    def __init__(self, messages=()) -> None:
        self._messages = list(messages)
        self.closed = False

    def recv_match(self, blocking=True, timeout=None):
        if self._messages:
            return self._messages.pop(0)
        return None

    def close(self) -> None:
        self.closed = True


def _pump(conn, **kw):
    return MavlinkCommandPump(FakeLink(), connection=conn, **kw)


def test_heartbeat_from_target_fires_callback():
    beats: list[int] = []
    pump = _pump(
        ScriptedConn(),
        target_system=1,
        target_component=1,
        on_heartbeat=lambda: beats.append(1),
    )
    assert pump._dispatch(FakeMsg("HEARTBEAT", sys=1, comp=1)) is True
    assert beats == [1]


def test_heartbeat_from_other_system_is_ignored():
    beats: list[int] = []
    pump = _pump(
        ScriptedConn(),
        target_system=1,
        target_component=1,
        on_heartbeat=lambda: beats.append(1),
    )
    assert pump._dispatch(FakeMsg("HEARTBEAT", sys=255, comp=1)) is False
    assert pump._dispatch(FakeMsg("HEARTBEAT", sys=1, comp=2)) is False
    assert beats == []


def test_heartbeat_without_callback_is_safe():
    pump = _pump(ScriptedConn(), on_heartbeat=None)
    assert pump._dispatch(FakeMsg("HEARTBEAT", sys=1, comp=1)) is True


def test_command_ack_is_queued_and_served_by_recv_ack():
    pump = _pump(ScriptedConn())
    assert pump._dispatch(FakeMsg("COMMAND_ACK", command=400, result=0, sys=3)) is True
    assert pump.recv_ack(timeout=0.1) == Ack(command=400, result=0, source_system=3)


def test_recv_ack_times_out_to_none_when_empty():
    pump = _pump(ScriptedConn())
    assert pump.recv_ack(timeout=0.0) is None


def test_unrelated_message_is_dropped():
    pump = _pump(ScriptedConn())
    assert pump._dispatch(FakeMsg("ATTITUDE")) is False


def test_drain_once_handles_none_and_read_errors():
    pump = _pump(ScriptedConn())
    assert pump._drain_once() is False  # ScriptedConn empty -> None

    class Boom:
        def recv_match(self, blocking=True, timeout=None):
            raise OSError("link dropped")

    boom = MavlinkCommandPump(FakeLink(), connection=Boom())
    assert boom._drain_once() is False  # error swallowed, pump survives


def test_send_delegates_to_link():
    link = FakeLink()
    pump = MavlinkCommandPump(link, connection=ScriptedConn())
    sentinel = object()
    pump.send(sentinel)
    assert link.sent == [sentinel]


def test_start_runs_reader_and_close_stops_it():
    link = FakeLink()
    beats: list[int] = []
    pump = MavlinkCommandPump(
        link,
        connection=ScriptedConn([FakeMsg("HEARTBEAT", sys=1, comp=1)]),
        on_heartbeat=lambda: beats.append(1),
        read_timeout_s=0.01,
    )
    pump.start()
    assert link.started is True
    # The reader thread should consume the scripted heartbeat promptly.
    deadline = threading.Event()
    for _ in range(200):
        if beats:
            break
        deadline.wait(0.01)
    assert beats == [1]
    pump.close()
    assert link.closed is True
    assert pump._thread is None
    pump.close()  # idempotent: second close is a no-op


def test_double_start_is_refused():
    pump = MavlinkCommandPump(FakeLink(), connection=ScriptedConn(), read_timeout_s=0.01)
    pump.start()
    try:
        with pytest.raises(RuntimeError):
            pump.start()  # a second reader would reintroduce the dual-reader race
    finally:
        pump.close()


def test_close_keeps_handle_when_reader_does_not_stop():
    link = FakeLink()
    pump = MavlinkCommandPump(link, connection=ScriptedConn())

    class StuckThread:
        def join(self, timeout=None) -> None:
            pass  # never actually stops

        def is_alive(self) -> bool:
            return True

    pump._thread = StuckThread()  # type: ignore[assignment]
    pump.close()
    # The handle is retained (not orphaned) but the link is still closed.
    assert pump._thread is not None
    assert link.closed is True
