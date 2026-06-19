"""The live pymavlink command link — the one piece that touches real hardware.

This is the production :class:`~meshsa.command.lifecycle.CommandLink`: it packs a
:class:`~meshsa.command.commands.CommandSpec` into a COMMAND_LONG/COMMAND_INT frame
*against the live ``MAVLink`` instance* (which owns the sequence counter and MAVLink2
signing state — see design §10) and reads COMMAND_ACK back.

The pymavlink connection is **injected** (real link in production, a fake in tests),
so the pack/translate/recv logic is fully testable hardware-free. Only the real
link construction and signing setup are ``# pragma: no cover`` glue. The connection
is typed ``Any`` because pymavlink ships no type stubs.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import structlog

from .commands import CommandSpec
from .lifecycle import Ack

_log = structlog.get_logger("meshsa.command.mavlink_link")


class MavlinkCommandLink:
    """Packs commands onto, and reads ACKs from, an injected pymavlink connection."""

    def __init__(
        self,
        *,
        connection: Any = None,
        connection_factory: Callable[[], Any] | None = None,
        target_system: int = 1,
        target_component: int = 1,
        signing_key: bytes | None = None,
        link_id: int = 0,
    ) -> None:
        if connection is None and connection_factory is None:
            raise ValueError("connection or connection_factory is required")
        self._conn = connection
        self._factory = connection_factory
        self._target_system = target_system
        self._target_component = target_component
        self._signing_key = signing_key
        self._link_id = link_id
        self._started = False

    def start(self) -> None:
        """Open the link (if a factory was given) and enable MAVLink2 signing.

        Must be called before :meth:`send`/:meth:`recv_ack`: MAVLink2 signing is set
        up here, so sending before ``start`` would silently transmit *unsigned*
        commands. The send/recv guards fail closed until this has run.
        """
        if self._conn is None:  # pragma: no cover - real link construction
            assert self._factory is not None
            self._conn = self._factory()
        if self._signing_key is not None:  # pragma: no cover - touches real mav
            self._conn.setup_signing(self._signing_key, link_id=self._link_id)
        self._started = True

    def send(self, spec: CommandSpec) -> None:
        """Pack ``spec`` as COMMAND_INT (positional) or COMMAND_LONG and transmit."""
        conn = self._require_conn()
        p = spec.params
        if spec.kind == "int":
            conn.mav.command_int_send(
                self._target_system,
                self._target_component,
                spec.frame,
                spec.command,
                0,  # current
                0,  # autocontinue
                p[0],
                p[1],
                p[2],
                p[3],
                spec.x,
                spec.y,
                spec.z,
            )
        else:
            conn.mav.command_long_send(
                self._target_system,
                self._target_component,
                spec.command,
                0,  # confirmation
                p[0],
                p[1],
                p[2],
                p[3],
                p[4],
                p[5],
                p[6],
            )

    def recv_ack(self, timeout: float) -> Ack | None:
        """Block up to ``timeout`` for a COMMAND_ACK; map it to an :class:`Ack`."""
        conn = self._require_conn()
        msg = conn.recv_match(type="COMMAND_ACK", blocking=True, timeout=timeout)
        if msg is None:
            return None
        return Ack(
            command=int(msg.command),
            result=int(msg.result),
            source_system=int(msg.get_srcSystem()),
        )

    def close(self) -> None:
        """Close the link (best-effort; idempotent)."""
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:  # pragma: no cover - best-effort teardown
                _log.warning("error closing command link", exc_info=True)
            self._conn = None

    def _require_conn(self) -> Any:
        if not self._started or self._conn is None:
            raise RuntimeError(
                "MavlinkCommandLink is not started; call start() before send/recv_ack "
                "(signing setup happens in start())"
            )
        return self._conn
