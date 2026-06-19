"""The production heartbeat-pump: the single owner of the autopilot socket.

A pymavlink connection has one byte stream and must have **one** reader: if the
:class:`~meshsa.command.lifecycle.CommandSender` polled it for COMMAND_ACK while a
separate thread polled it for HEARTBEAT, the two ``recv_match`` loops would steal
each other's messages. :class:`MavlinkCommandPump` resolves that by being the sole
reader. One background thread drains the link and fans messages out:

* ``COMMAND_ACK`` -> an internal queue, served by :meth:`recv_ack` (so the pump *is*
  the :class:`~meshsa.command.lifecycle.CommandLink` the sender talks to).
* ``HEARTBEAT`` from the target vehicle -> ``on_heartbeat`` (feeds
  :class:`~meshsa.command.health.HeartbeatHealth`, so the pre-arm interlock finally
  has live data instead of failing closed).

It delegates *sending* to an injected :class:`MavlinkCommandLink` (which owns the
pack/sign logic against the live ``MAVLink`` instance), so there is exactly one
reader and one writer on the shared connection. The connection is injected (a fake
in tests), so the dispatch fan-out is fully testable hardware-free; only the thread
plumbing is light enough to exercise with a scripted fake.
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from typing import Any

import structlog

from .lifecycle import Ack
from .mavlink_link import MavlinkCommandLink

_log = structlog.get_logger("meshsa.command.mavlink_pump")


class MavlinkCommandPump:
    """Sole reader of the autopilot link; routes ACKs to the sender, beats to health."""

    def __init__(
        self,
        link: MavlinkCommandLink,
        *,
        connection: Any,
        target_system: int = 1,
        target_component: int = 1,
        on_heartbeat: Callable[[], None] | None = None,
        read_timeout_s: float = 0.5,
    ) -> None:
        self._link = link
        self._conn = connection
        self._target_system = target_system
        self._target_component = target_component
        self._on_heartbeat = on_heartbeat
        self._read_timeout_s = read_timeout_s
        self._acks: queue.Queue[Ack] = queue.Queue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the send link (signing) and spawn the single reader thread.

        Refuses a second concurrent start: a second reader thread on one connection
        would reintroduce the dual-reader race this class exists to prevent.
        """
        if self._thread is not None:
            raise RuntimeError("MavlinkCommandPump is already started")
        self._stop.clear()
        self._link.start()
        thread = threading.Thread(target=self._run, name="cmd-mav-pump", daemon=True)
        self._thread = thread
        thread.start()

    # --- CommandLink seam (what CommandSender drives) --------------------------

    def send(self, spec: Any) -> None:
        """Delegate to the send link (the only writer on the connection)."""
        self._link.send(spec)

    def recv_ack(self, timeout: float) -> Ack | None:
        """Pop the next COMMAND_ACK the reader queued, or ``None`` within ``timeout``."""
        try:
            return self._acks.get(timeout=max(0.0, timeout))
        except queue.Empty:
            return None

    # --- reader thread ---------------------------------------------------------

    def _run(self) -> None:  # pragma: no cover - thread loop exercised via _drain_once
        while not self._stop.is_set():
            if not self._drain_once():
                continue

    def _drain_once(self) -> bool:
        """Read one message and dispatch it. Returns False on timeout/error/no-op."""
        try:
            msg = self._conn.recv_match(blocking=True, timeout=self._read_timeout_s)
        except Exception:  # a transient link read error must not kill the pump
            _log.warning("command pump read error", exc_info=True)
            return False
        if msg is None:
            return False
        return self._dispatch(msg)

    def _dispatch(self, msg: Any) -> bool:
        """Route one parsed message; returns True if it was a heartbeat or ACK."""
        mtype = msg.get_type()
        if mtype == "HEARTBEAT":
            # Only the autopilot's own heartbeats gate arming; ignore GCS/peer beats.
            if (
                msg.get_srcSystem() == self._target_system
                and msg.get_srcComponent() == self._target_component
            ):
                if self._on_heartbeat is not None:
                    self._on_heartbeat()
                return True
            return False
        if mtype == "COMMAND_ACK":
            self._acks.put(
                Ack(
                    command=int(msg.command),
                    result=int(msg.result),
                    source_system=int(msg.get_srcSystem()),
                )
            )
            return True
        return False

    def close(self) -> None:
        """Stop the reader thread and close the underlying link (idempotent).

        The thread handle is cleared only once the reader has actually stopped; if
        the join times out the handle is kept (and a warning logged) so a still-
        running reader stays observable rather than being silently orphaned.
        """
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=self._read_timeout_s + 2.0)
            if thread.is_alive():
                _log.warning("command pump reader did not stop within join timeout")
            else:
                self._thread = None
        self._link.close()
