"""Characterization pins for the four transport constructors (plan P2-4, design D-8).

Every keyword the ``TakTcpTransport``, ``MeshtasticTransport``, ``MspSourceTransport`` and
``MavlinkSourceTransport`` constructors accept is pinned here by the attribute it resolves
to, with the keyword call shape existing call sites use. The pins landed *before* the
constructors gained their ``*Options`` models so the migration diff shows that every
keyword still lands where it did; the Options-based constructions are asserted to resolve
identically once they exist.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from meshsa import transport_registry
from meshsa.defaults import (
    DEFAULT_BACKOFF_FACTOR,
    DEFAULT_BACKOFF_INITIAL_S,
    DEFAULT_BACKOFF_MAX_S,
    DEFAULT_LOCAL_TARGET_HOST,
    DEFAULT_QUEUE_MAXSIZE,
    PORT_FTS_TCP,
    PORT_TAK_TLS,
)
from meshsa.transports._options import resolve_options
from meshsa.transports.mavlink_source import MavlinkSourceOptions, MavlinkSourceTransport
from meshsa.transports.meshtastic_radio import MeshtasticOptions, MeshtasticTransport
from meshsa.transports.msp_source import MspOptions, MspSourceTransport
from meshsa.transports.tak import TakTcpOptions, TakTcpTransport


async def _never_connect() -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    raise AssertionError("the pins never open a connection")


def _backoff(transport: Any) -> tuple[float, float, float]:
    backoff = transport._backoff
    return backoff._initial, backoff._max, backoff._factor


# ── TakTcpTransport ──────────────────────────────────────────────────────────


def test_tak_tcp_keyword_defaults() -> None:
    t = TakTcpTransport(connector=_never_connect)
    assert t.name == "tak_tcp"
    assert (t.host, t.port, t.tls) == (DEFAULT_LOCAL_TARGET_HOST, PORT_FTS_TCP, False)
    assert t._ssl_context is None
    assert t._read_size == 4096
    assert t._delimiter == b""
    assert t._reconnect is True
    assert _backoff(t) == (DEFAULT_BACKOFF_INITIAL_S, DEFAULT_BACKOFF_MAX_S, DEFAULT_BACKOFF_FACTOR)
    assert t._pacer is None
    assert t._inbox.maxsize == DEFAULT_QUEUE_MAXSIZE
    assert t._connector is _never_connect


def test_tak_tcp_keyword_overrides_land_on_the_transport() -> None:
    t = TakTcpTransport(
        name="tak-9",
        connector=_never_connect,
        host="tls://tak.example:9000",
        pacing=True,
        pacing_rate_hz=5.0,
        pacing_burst=2,
        read_size=1024,
        delimiter=b"\n",
        reconnect=False,
        backoff_initial_s=0.5,
        backoff_max_s=4.0,
        backoff_factor=3.0,
        queue_maxsize=7,
    )
    assert t.name == "tak-9"
    assert (t.host, t.port, t.tls) == ("tak.example", 9000, True)
    assert t._ssl_context is None  # a connector is injected, so no context is built
    assert t._read_size == 1024
    assert t._delimiter == b"\n"
    assert t._reconnect is False
    assert _backoff(t) == (0.5, 4.0, 3.0)
    assert t._pacer is not None
    assert (t._pacer._interval, t._pacer._capacity) == (0.2, 2.0)
    assert t._inbox.maxsize == 7


def test_tak_tcp_tls_flag_resolves_the_tls_port_and_builds_a_context_only_without_connector() -> (
    None
):
    import ssl

    ctx = ssl.create_default_context()
    t = TakTcpTransport(tls=True, ssl_context_factory=lambda: ctx)
    assert (t.port, t.tls) == (PORT_TAK_TLS, True)
    assert t._ssl_context is ctx
    assert TakTcpTransport(host="tcp://h:1", connector=_never_connect).tls is False


def test_tak_tcp_unknown_keywords_are_ignored() -> None:
    t = TakTcpTransport(connector=_never_connect, bogus_option=1)
    assert t.host == DEFAULT_LOCAL_TARGET_HOST


def test_tak_tcp_registry_factory_passes_keywords_through() -> None:
    t = transport_registry.create("tak_tcp", name="x", connector=_never_connect, read_size=99)
    assert isinstance(t, TakTcpTransport)
    assert (t.name, t._read_size) == ("x", 99)


# ── MeshtasticTransport ──────────────────────────────────────────────────────


def test_meshtastic_keyword_defaults() -> None:
    t = MeshtasticTransport(interface_factory=lambda: object())
    assert t.name == "meshtastic"
    assert (t.portnum, t.portnum_name) == (256, "PRIVATE_APP")
    assert (t.destination, t.want_ack, t.channel_index) == ("^all", False, 0)
    assert (t._topic, t._lost_topic) == ("meshtastic.receive", "meshtastic.connection.lost")
    assert t._reconnect is True
    assert t._mesh is None
    assert _backoff(t) == (DEFAULT_BACKOFF_INITIAL_S, DEFAULT_BACKOFF_MAX_S, DEFAULT_BACKOFF_FACTOR)
    assert t._inbox.maxsize == DEFAULT_QUEUE_MAXSIZE
    assert t._subscribe is None and t._unsubscribe is None


def test_meshtastic_keyword_overrides_land_on_the_transport() -> None:
    def sub(_cb: Any, _topic: str) -> None:
        pass

    mesh = {"region": "EU_868", "channel": "ops"}
    t = MeshtasticTransport(
        name="lora",
        interface_factory=lambda: object(),
        subscribe=sub,
        unsubscribe=sub,
        topic="t.rx",
        lost_topic="t.lost",
        portnum=42,
        portnum_name="X",
        destination="!abcd",
        want_ack=True,
        channel_index=2,
        reconnect=False,
        backoff_initial_s=0.1,
        backoff_max_s=1.0,
        backoff_factor=4.0,
        queue_maxsize=3,
        mesh=mesh,
    )
    assert t.name == "lora"
    assert (t.portnum, t.portnum_name) == (42, "X")
    assert (t.destination, t.want_ack, t.channel_index) == ("!abcd", True, 2)
    assert (t._topic, t._lost_topic) == ("t.rx", "t.lost")
    assert t._reconnect is False
    assert t._mesh == mesh
    assert _backoff(t) == (0.1, 1.0, 4.0)
    assert t._inbox.maxsize == 3
    assert t._subscribe is sub and t._unsubscribe is sub


def test_meshtastic_registry_factory_passes_keywords_through() -> None:
    t = transport_registry.create(
        "meshtastic", name="m", interface_factory=lambda: object(), portnum=7, connection="tcp"
    )
    assert isinstance(t, MeshtasticTransport)
    assert (t.name, t.portnum) == ("m", 7)


# ── MspSourceTransport ───────────────────────────────────────────────────────


def test_msp_keyword_defaults() -> None:
    board = object()
    t = MspSourceTransport(board=board)
    assert t.name == "msp"
    assert t._resource is board
    assert (t._source_uid, t._callsign) == ("fc-1", "fc-1")
    assert (t._coord_scale, t._alt_scale) == (1e7, 1.0)
    assert t._poll_wait_s == 1.0
    assert (t._log_every_n, t._log_interval_s) == (100, 30.0)
    assert t._inbox.maxsize == DEFAULT_QUEUE_MAXSIZE


def test_msp_keyword_overrides_land_on_the_transport() -> None:
    board = object()

    def poll(_board: Any) -> dict[str, Any] | None:
        return None

    t = MspSourceTransport(
        name="fc",
        board=board,
        poll=poll,
        source_uid="fc-9",
        callsign="FC9",
        coord_scale=1.0,
        alt_scale=2.0,
        poll_interval_s=0.25,
        queue_maxsize=5,
        log_every_n=7,
        log_interval_s=3.0,
    )
    assert t.name == "fc"
    assert t._resource is board
    assert t._poll_fn is poll
    assert (t._source_uid, t._callsign) == ("fc-9", "FC9")
    assert (t._coord_scale, t._alt_scale) == (1.0, 2.0)
    assert t._poll_wait_s == 0.25
    assert (t._log_every_n, t._log_interval_s) == (7, 3.0)
    assert t._inbox.maxsize == 5


def test_msp_registry_factory_passes_keywords_through() -> None:
    t = transport_registry.create(
        "msp_source", name="fc", board=object(), alt_scale=0.5, device="/dev/x"
    )
    assert isinstance(t, MspSourceTransport)
    assert (t.name, t._alt_scale) == ("fc", 0.5)


# ── MavlinkSourceTransport ───────────────────────────────────────────────────


def test_mavlink_keyword_defaults() -> None:
    conn = object()
    t = MavlinkSourceTransport(connection=conn)
    assert t.name == "mavlink"
    assert t._resource is conn
    assert t._message_type == "GLOBAL_POSITION_INT"
    assert (t._source_uid, t._callsign) == ("mav-1", "mav-1")
    assert (t._coord_scale, t._alt_scale) == (1e7, 1e-3)
    assert t._recv_timeout == 1.0
    assert t._poll_wait_s == 0.0  # the blocking recv paces the loop
    assert t._inbox.maxsize == DEFAULT_QUEUE_MAXSIZE


def test_mavlink_keyword_overrides_land_on_the_transport() -> None:
    conn = object()
    t = MavlinkSourceTransport(
        name="mav",
        connection=conn,
        message_type="GPS_RAW_INT",
        source_uid="mav-9",
        callsign="MAV9",
        coord_scale=1.0,
        alt_scale=1.0,
        recv_timeout_s=0.5,
        queue_maxsize=4,
        endpoint="udpin:127.0.0.1:14550",
    )
    assert t.name == "mav"
    assert t._resource is conn
    assert t._message_type == "GPS_RAW_INT"
    assert (t._source_uid, t._callsign) == ("mav-9", "MAV9")
    assert (t._coord_scale, t._alt_scale) == (1.0, 1.0)
    assert t._recv_timeout == 0.5
    assert t._inbox.maxsize == 4


def test_mavlink_non_loopback_endpoint_without_token_still_fails_closed() -> None:
    with pytest.raises(ValueError, match="without a token"):
        MavlinkSourceTransport(connection=object(), endpoint="udpin:0.0.0.0:14550")
    MavlinkSourceTransport(connection=object(), endpoint="udpin:0.0.0.0:14550", token="t")


def test_mavlink_registry_factory_passes_keywords_through() -> None:
    t = transport_registry.create("mavlink_source", name="mav", connection=object(), alt_scale=2.0)
    assert isinstance(t, MavlinkSourceTransport)
    assert (t.name, t._alt_scale) == ("mav", 2.0)


# ── the *Options form (plan P2-4): one model, same resolution as the keywords ─


def test_tak_tcp_options_model_resolves_like_the_keywords() -> None:
    options = TakTcpOptions(
        connector=_never_connect,
        host="tls://tak.example:9000",
        pacing=True,
        pacing_rate_hz=5.0,
        pacing_burst=2,
        read_size=1024,
        delimiter=b"\n",
        reconnect=False,
        backoff_initial_s=0.5,
        backoff_max_s=4.0,
        backoff_factor=3.0,
        queue_maxsize=7,
    )
    t = TakTcpTransport("tak-9", options)
    assert t.options == options
    assert (t.host, t.port, t.tls) == ("tak.example", 9000, True)
    assert (t._read_size, t._delimiter, t._reconnect) == (1024, b"\n", False)
    assert _backoff(t) == (0.5, 4.0, 3.0)
    assert t._pacer is not None and t._pacer._capacity == 2.0
    assert t._inbox.maxsize == 7
    # A keyword beside the model overrides that one field and leaves the rest.
    tweaked = TakTcpTransport("tak-9", options, read_size=1)
    assert tweaked._read_size == 1
    assert tweaked.options == TakTcpOptions(**{**options.__dict__, "read_size": 1})
    assert TakTcpTransport(connector=_never_connect).options == TakTcpOptions(
        connector=_never_connect
    )


def test_meshtastic_options_model_resolves_like_the_keywords() -> None:
    factory = object
    options = MeshtasticOptions(
        interface_factory=factory, portnum=42, want_ack=True, mesh={"region": "EU_868"}
    )
    t = MeshtasticTransport("lora", options)
    assert t.options == options
    assert (t.portnum, t.want_ack, t._mesh) == (42, True, {"region": "EU_868"})
    assert t._factory is factory


def test_msp_options_model_resolves_like_the_keywords() -> None:
    board = object()
    options = MspOptions(board=board, source_uid="fc-9", alt_scale=2.0, poll_interval_s=0.25)
    t = MspSourceTransport("fc", options)
    assert t.options == options
    assert t._resource is board
    assert (t._source_uid, t._alt_scale, t._poll_wait_s) == ("fc-9", 2.0, 0.25)


def test_mavlink_options_model_resolves_like_the_keywords() -> None:
    conn = object()
    options = MavlinkSourceOptions(connection=conn, message_type="GPS_RAW_INT", recv_timeout_s=0.5)
    t = MavlinkSourceTransport("mav", options, endpoint="udpin:127.0.0.1:14550")
    assert t.options == options
    assert t._resource is conn
    assert (t._message_type, t._recv_timeout) == ("GPS_RAW_INT", 0.5)
    with pytest.raises(ValueError, match="without a token"):
        MavlinkSourceTransport("mav", options, endpoint="udpin:0.0.0.0:14550")


def test_registry_factories_build_the_model_and_forward_extras() -> None:
    board = object()
    t = transport_registry.create("msp_source", board=board, alt_scale=0.5, device="/dev/x")
    assert isinstance(t, MspSourceTransport)
    assert t.options == MspOptions(board=board, alt_scale=0.5)  # ``device`` is an extra


# ── resolve_options ───────────────────────────────────────────────────────────


def test_resolve_options_splits_fields_from_extras_and_applies_overrides() -> None:
    resolved, extras = resolve_options(
        MspOptions, None, {"alt_scale": 2.0, "device": "/dev/x", "baudrate": 9600}
    )
    assert resolved == MspOptions(alt_scale=2.0)
    assert extras == {"device": "/dev/x", "baudrate": 9600}
    base = MspOptions(alt_scale=3.0, source_uid="fc-3")
    resolved, extras = resolve_options(MspOptions, base, {"alt_scale": 4.0})
    assert resolved == MspOptions(alt_scale=4.0, source_uid="fc-3")  # override wins, rest kept
    assert extras == {}
    assert resolve_options(MspOptions, base, {}) == (base, {})  # no override: the model itself


def test_options_models_are_frozen() -> None:
    options = TakTcpOptions()
    with pytest.raises(AttributeError):
        options.host = "x"  # type: ignore[misc]


def test_a_stray_options_key_in_overrides_is_dropped_not_fatal(caplog: Any) -> None:
    """A config dict carrying an ``options`` key must degrade, not abort build_node()."""
    resolved, extras = resolve_options(MspOptions, None, {"options": {"x": 1}, "device": "/dev/x"})
    assert resolved == MspOptions()
    assert extras == {"device": "/dev/x"}
    # The registry path is where a config-file key lands.
    transport = transport_registry.create("msp_source", name="fc", options={"alt_scale": 2.0})
    assert isinstance(transport, MspSourceTransport)
    assert transport.options == MspOptions()  # the dict is not a model: dropped


def test_a_model_under_the_options_key_is_adopted_when_no_model_was_given() -> None:
    model = MspOptions(alt_scale=5.0)
    resolved, extras = resolve_options(MspOptions, None, {"options": model, "alt_scale": 6.0})
    assert resolved == MspOptions(alt_scale=6.0)  # adopted as the base; override still wins
    assert extras == {}
    other = MspOptions(alt_scale=1.0)
    resolved, _ = resolve_options(MspOptions, other, {"options": model})
    assert resolved == other  # an explicit model is never displaced


def test_meshtastic_options_repr_does_not_print_the_mesh_psk() -> None:
    options = MeshtasticOptions(mesh={"psk": "SECRETPSK", "channel": 7})
    assert "SECRETPSK" not in repr(options)
    assert options.mesh == {"psk": "SECRETPSK", "channel": 7}  # the value itself is intact
