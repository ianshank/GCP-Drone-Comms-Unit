"""MavlinkCommandLink pack/recv logic (fakes-only; injected fake connection)."""

import pytest

from meshsa.command import Ack, MavlinkCommandLink
from meshsa.command.commands import _goto, _rtl


class FakeMav:
    def __init__(self) -> None:
        self.long: list[tuple] = []
        self.int: list[tuple] = []

    def command_long_send(self, *args) -> None:
        self.long.append(args)

    def command_int_send(self, *args) -> None:
        self.int.append(args)


class FakeAck:
    def __init__(self, command: int, result: int, src: int = 1) -> None:
        self.command = command
        self.result = result
        self._src = src

    def get_srcSystem(self) -> int:
        return self._src


class FakeConn:
    def __init__(self, ack=None) -> None:
        self.mav = FakeMav()
        self._ack = ack
        self.closed = False

    def recv_match(self, type=None, blocking=True, timeout=None):
        return self._ack

    def close(self) -> None:
        self.closed = True


def test_requires_connection_or_factory():
    with pytest.raises(ValueError):
        MavlinkCommandLink()


def test_start_is_safe_with_injected_connection_and_no_signing():
    # Exercises start()'s guard lines without touching real-link/signing pragmas.
    link = MavlinkCommandLink(connection=FakeConn(), target_system=1)
    link.start()


def test_send_long_packs_command_long():
    conn = FakeConn()
    link = MavlinkCommandLink(connection=conn, target_system=7, target_component=3)
    link.start()
    link.send(_rtl())  # kind="long", command=20
    assert len(conn.mav.long) == 1
    args = conn.mav.long[0]
    assert args[0] == 7  # target_system
    assert args[1] == 3  # target_component
    assert args[2] == 20  # command (RTL)
    assert args[3] == 0  # confirmation
    assert args[4:] == (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)  # p1..p7
    assert conn.mav.int == []


def test_send_int_packs_command_int_with_positional_fields():
    conn = FakeConn()
    link = MavlinkCommandLink(connection=conn, target_system=1, target_component=1)
    link.start()
    link.send(_goto(lat_deg=37.0, lon_deg=-122.0, alt_m=25.0))  # kind="int"
    assert len(conn.mav.int) == 1
    args = conn.mav.int[0]
    assert args[3] == 192  # MAV_CMD_DO_REPOSITION
    assert args[4] == 0 and args[5] == 0  # current, autocontinue
    assert args[6] == -1.0  # param1 default ground speed
    assert args[10] == 370000000  # x = lat degE7
    assert args[11] == -1220000000  # y = lon degE7
    assert args[12] == 25.0  # z = alt


def test_recv_ack_maps_message_fields():
    conn = FakeConn(ack=FakeAck(command=400, result=0, src=3))
    link = MavlinkCommandLink(connection=conn)
    link.start()
    ack = link.recv_ack(timeout=1.0)
    assert ack == Ack(command=400, result=0, source_system=3)


def test_recv_ack_returns_none_on_timeout():
    link = MavlinkCommandLink(connection=FakeConn(ack=None))
    link.start()
    assert link.recv_ack(timeout=0.1) is None


def test_send_before_start_raises():
    # Fail closed: sending before start() would skip signing setup (unsigned frames).
    link = MavlinkCommandLink(connection=FakeConn())
    with pytest.raises(RuntimeError):
        link.send(_rtl())
    with pytest.raises(RuntimeError):
        link.recv_ack(timeout=0.1)


def test_close_then_use_raises():
    conn = FakeConn()
    link = MavlinkCommandLink(connection=conn)
    link.start()
    link.close()
    link.close()  # idempotent: second close with conn already None is a no-op
    assert conn.closed is True
    with pytest.raises(RuntimeError):
        link.send(_rtl())
