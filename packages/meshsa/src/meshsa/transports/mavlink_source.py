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
  * Nothing is hard-coded: endpoint, message type, identity, recv timeout, the
    coordinate/altitude wire scales and the clock are all parameters/config
    options. The GPS scales are configurable (mirroring ``msp_source``) so a
    non-standard MAVLink dialect never needs a code change; the defaults match the
    common ``GLOBAL_POSITION_INT`` units (lat/lon degE7, altitude millimetres).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import structlog

from ..defaults import DEFAULT_MAVLINK_ENDPOINT, DEFAULT_QUEUE_MAXSIZE
from ..protocols import Clock
from ..registry import transport_registry
from ._options import resolve_options
from .polling_source import PollingSourceTransport

ConnectionFactory = Callable[[], Any]

_log = structlog.get_logger("meshsa.mavlink_source")


def _default_connection_factory(
    options: dict[str, Any],
) -> ConnectionFactory:  # pragma: no cover - real hardware default factory
    def factory() -> Any:
        from pymavlink import mavutil

        endpoint = options.get("endpoint", DEFAULT_MAVLINK_ENDPOINT)
        return mavutil.mavlink_connection(endpoint)

    return factory


def _extract_endpoint_host(endpoint: str) -> str | None:
    """Extract host string from network endpoints like 'udpin:0.0.0.0:14550' or 'tcpin:127.0.0.1:5760'."""
    if not endpoint:
        return None
    spec = endpoint
    for prefix in ("udpin:", "udpout:", "tcpin:", "tcpout:", "udp:", "tcp:"):
        if spec.startswith(prefix):
            spec = spec[len(prefix) :]
            break
    if ":" in spec:
        host, _, _port = spec.partition(":")
        if host:
            return host
    return None


@dataclass(frozen=True, kw_only=True)
class MavlinkSourceOptions:
    """Every ``MavlinkSourceTransport`` tunable, with its default (plan P2-4; see ``_options``).

    ``endpoint`` and ``token`` are deliberately *not* fields: they are the connection
    factory's keys and the bind-check inputs, read from the extras exactly as before so
    the fail-closed check in the constructor sees the same values the factory does.
    """

    connection: Any | None = None
    connection_factory: ConnectionFactory | None = None
    message_type: str = "GLOBAL_POSITION_INT"
    source_uid: str = "mav-1"
    callsign: str | None = None
    coord_scale: float = 1e7
    alt_scale: float = 1e-3
    recv_timeout_s: float = 1.0
    clock: Clock | None = None
    queue_maxsize: int = DEFAULT_QUEUE_MAXSIZE


class MavlinkSourceTransport(PollingSourceTransport):
    _thread_prefix = "mavlink"

    def __init__(
        self, name: str = "mavlink", options: MavlinkSourceOptions | None = None, **overrides: Any
    ) -> None:
        """Build the transport from a :class:`MavlinkSourceOptions` and/or its fields as keywords.

        The ``endpoint``/``token`` extras drive the fail-closed bind check before any
        resource is touched (a non-loopback ingest without a token is refused).
        """
        opts, extras = resolve_options(MavlinkSourceOptions, options, overrides)
        #: The resolved options (exposed for observability/tests).
        self.options = opts
        endpoint = str(extras.get("endpoint", DEFAULT_MAVLINK_ENDPOINT))
        token = extras.get("token")
        host = _extract_endpoint_host(endpoint)
        if host:
            from ..netauth import validate_bind

            validate_bind(
                host,
                token,
                service="the MAVLink source transport",
                remedy="set 'token' in transport options or bind to loopback (127.0.0.1)",
            )
        super().__init__(
            name,
            resource=opts.connection,
            factory=opts.connection_factory or _default_connection_factory(extras),
            source_uid=opts.source_uid,
            callsign=opts.callsign,
            clock=opts.clock,
            queue_maxsize=opts.queue_maxsize,
            # The blocking recv_match (below) paces the loop; no extra wait needed.
            poll_wait_s=0.0,
        )
        self._message_type = opts.message_type
        self._coord_scale = opts.coord_scale
        self._alt_scale = opts.alt_scale
        self._recv_timeout = opts.recv_timeout_s

    def _poll(self, resource: Any) -> list[bytes]:
        msg = resource.recv_match(
            type=self._message_type, blocking=True, timeout=self._recv_timeout
        )
        if msg is None:
            return []  # idle/timeout — re-check the stop event and poll again
        lat = getattr(msg, "lat", None)
        lon = getattr(msg, "lon", None)
        alt = getattr(msg, "alt", None)
        if lat is None or lon is None or alt is None:
            # A partial/foreign message lacking position fields must not raise an
            # AttributeError: the base reader (polling_source._reader) treats any
            # poll exception as fatal and stops the thread. Drop it and keep
            # polling, mirroring crsf_source's per-frame drop-and-continue.
            _log.warning("mavlink message missing position fields; dropping", transport=self.name)
            return []
        return [
            self._position_frame(
                lat / self._coord_scale,  # default degE7 -> degrees
                lon / self._coord_scale,
                alt * self._alt_scale,  # default mm -> metres (1e-3)
            )
        ]


@transport_registry.register("mavlink_source")
def _make_mavlink_source(name: str = "mavlink", **options: Any) -> MavlinkSourceTransport:
    opts, extras = resolve_options(MavlinkSourceOptions, None, options)
    return MavlinkSourceTransport(name, opts, **extras)
