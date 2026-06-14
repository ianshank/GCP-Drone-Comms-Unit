"""MAVLink telemetry source transport (real pymavlink API).

A receive-only transport that ingests autopilot telemetry from a MAVLink endpoint
(typically a proxy's UDP output such as ``udpin:127.0.0.1:14550``, or a serial
link) and turns each position fix into a structured telemetry frame for the
``telemetry`` codec. Paired with a ``cot`` codec on a TAK leg, a drone shows up as
an ATAK track with no core changes.

Built on :class:`~meshsa.transports.polling_source.PollingSourceTransport` (which
owns the reader thread, event-based shutdown and the frame builder). This module
supplies only the MAVLink specifics:
  * The **stateful** MAVLink parse lives here because pymavlink is stream/poll
    oriented; the ``telemetry`` codec stays a pure per-frame map. ``recv_match``
    blocks up to ``recv_timeout_s`` and so paces the reader itself — no extra
    inter-poll wait is needed (``poll_wait_s`` is left at ``0``).
  * The pymavlink connection is **injected** (``connection`` / ``connection_factory``)
    so the logic is tested with a fake; only the real link builder is
    ``# pragma: no cover``.
  * Nothing is hard-coded: endpoint, message type, identity, recv timeout and the
    clock are all parameters/config options.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..protocols import Clock
from ..registry import transport_registry
from .polling_source import PollingSourceTransport

ConnectionFactory = Callable[[], Any]


def _default_connection_factory(options: dict[str, Any]) -> ConnectionFactory:  # pragma: no cover
    def factory() -> Any:
        from pymavlink import mavutil

        endpoint = options.get("endpoint", "udpin:127.0.0.1:14550")
        return mavutil.mavlink_connection(endpoint)

    return factory


class MavlinkSourceTransport(PollingSourceTransport):
    _thread_prefix = "mavlink"

    def __init__(
        self,
        name: str = "mavlink",
        *,
        connection: Any | None = None,
        connection_factory: ConnectionFactory | None = None,
        message_type: str = "GLOBAL_POSITION_INT",
        source_uid: str = "mav-1",
        callsign: str | None = None,
        recv_timeout_s: float = 1.0,
        clock: Clock | None = None,
        queue_maxsize: int = 1000,
        **_options: Any,
    ) -> None:
        super().__init__(
            name,
            resource=connection,
            factory=connection_factory or _default_connection_factory(_options),
            source_uid=source_uid,
            callsign=callsign,
            clock=clock,
            queue_maxsize=queue_maxsize,
            # The blocking recv_match (below) paces the loop; no extra wait needed.
            poll_wait_s=0.0,
        )
        self._message_type = message_type
        self._recv_timeout = recv_timeout_s

    def _poll(self, resource: Any) -> list[bytes]:
        msg = resource.recv_match(
            type=self._message_type, blocking=True, timeout=self._recv_timeout
        )
        if msg is None:
            return []  # idle/timeout — re-check the stop event and poll again
        return [
            self._position_frame(
                msg.lat / 1e7,  # degE7 -> degrees
                msg.lon / 1e7,
                msg.alt / 1000.0,  # mm -> metres
            )
        ]


@transport_registry.register("mavlink_source")
def _make_mavlink_source(name: str = "mavlink", **options: Any) -> MavlinkSourceTransport:
    return MavlinkSourceTransport(name=name, **options)
