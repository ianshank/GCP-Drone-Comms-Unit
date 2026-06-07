"""Meshtastic radio transport (real Python API) with serial reconnect/backoff.

Wraps a Meshtastic device interface (serial/TCP/BLE) and the pypubsub bus, both
injected so the logic is tested hermetically. A supervisor rebuilds the interface
with exponential backoff when the device drops: it listens for Meshtastic's
``connection.lost`` pubsub event and re-establishes the link. ``start()`` brings up
the first connection before returning; while disconnected, sends are best-effort
dropped rather than raising.

Threading: pubsub callbacks fire on the radio reader thread, so inbound bytes and
the lost-signal cross into the asyncio loop via ``call_soon_threadsafe``. Nothing is
hard-coded — connection/port, portnum, destination, channel, topics and the backoff
schedule come from config options.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from typing import Any, cast

import structlog

from ..protocols import SleepFn
from ..registry import transport_registry
from .base import AbstractTransport

_log = structlog.get_logger("meshsa.meshtastic")

InterfaceFactory = Callable[[], Any]
SubscribeFn = Callable[[Callable[..., None], str], None]
#: Applies node mesh settings (region/channel/psk/freq_khz) to a live device.
Provisioner = Callable[[Any, dict[str, Any]], None]


def _default_interface_factory(options: dict[str, Any]) -> InterfaceFactory:  # pragma: no cover
    def factory() -> Any:
        connection = options.get("connection", "serial")
        if connection == "serial":
            from meshtastic.serial_interface import SerialInterface

            return SerialInterface(devPath=options.get("port"))
        if connection == "tcp":
            from meshtastic.tcp_interface import TCPInterface

            return TCPInterface(hostname=options["host"])
        raise ValueError(f"unknown meshtastic connection {connection!r}")

    return factory


def _default_pubsub() -> tuple[SubscribeFn, SubscribeFn]:  # pragma: no cover - needs pypubsub
    from pubsub import pub

    # pypubsub's subscribe/unsubscribe carry richer signatures than SubscribeFn;
    # cast to the structural type the transport relies on.
    return cast(SubscribeFn, pub.subscribe), cast(SubscribeFn, pub.unsubscribe)


def _default_provisioner(iface: Any, mesh: dict[str, Any]) -> None:
    """Apply node mesh settings to a Meshtastic device's persistent config.

    Region/channel/PSK/frequency are device-level radio config, not per-send
    parameters, so the region is written to the attached node's ``localConfig``
    and persisted via ``writeConfig``. Scope note (no hardware yet): only the
    region is applied here, as a passthrough — the exact region value mapping
    (string vs. firmware enum) and the channel/PSK/frequency channel-set API
    vary by firmware and must be verified on hardware; those are logged as
    pending rather than silently claimed. The control flow is exercised by unit
    tests with a fake device; a fake provisioner can also be injected wholesale.
    """
    node = getattr(iface, "localNode", None)
    if node is None:
        _log.warning("meshtastic device exposes no localNode; cannot provision mesh")
        return
    region = mesh.get("region")
    if region:
        node.localConfig.lora.region = region
        node.writeConfig("lora")
    if any(mesh.get(k) for k in ("channel", "psk", "freq_khz")):
        _log.info(
            "mesh channel/psk/freq are device-provisioned; verify on hardware",
            channel=mesh.get("channel"),
            freq_khz=mesh.get("freq_khz"),
        )


class MeshtasticTransport(AbstractTransport):
    def __init__(
        self,
        name: str = "meshtastic",
        *,
        interface_factory: InterfaceFactory | None = None,
        subscribe: SubscribeFn | None = None,
        unsubscribe: SubscribeFn | None = None,
        topic: str = "meshtastic.receive",
        lost_topic: str = "meshtastic.connection.lost",
        portnum: int = 256,  # PRIVATE_APP
        portnum_name: str = "PRIVATE_APP",
        destination: str = "^all",
        want_ack: bool = False,
        channel_index: int = 0,
        reconnect: bool = True,
        backoff_initial_s: float = 1.0,
        backoff_max_s: float = 30.0,
        backoff_factor: float = 2.0,
        sleep: SleepFn | None = None,
        queue_maxsize: int = 1000,
        mesh: dict[str, Any] | None = None,
        provision: Provisioner | None = None,
        **options: Any,
    ) -> None:
        super().__init__(name, queue_maxsize)
        # `mesh` is an explicit param (not left in **options) so it never leaks
        # into the interface factory; provisioning is an injectable seam.
        self._mesh = mesh
        self._provision = provision or _default_provisioner
        self._factory = interface_factory or _default_interface_factory(options)
        if subscribe is None or unsubscribe is None:  # pragma: no cover - lib glue
            subscribe, unsubscribe = _default_pubsub()
        self._subscribe = subscribe
        self._unsubscribe = unsubscribe
        self._topic = topic
        self._lost_topic = lost_topic
        self.portnum = portnum
        self.portnum_name = portnum_name
        self.destination = destination
        self.want_ack = want_ack
        self.channel_index = channel_index
        self._reconnect = reconnect
        self._backoff_initial = backoff_initial_s
        self._backoff_max = backoff_max_s
        self._backoff_factor = backoff_factor
        self._sleep = sleep or asyncio.sleep
        self._iface: Any | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task[None] | None = None
        self._lost: asyncio.Event | None = None
        self._started = False
        self._stopping = False
        self._subscribed = False
        #: Times the supervisor (re)established the interface (observability).
        self.reconnects = 0

    async def start(self) -> None:
        await super().start()
        self._loop = asyncio.get_running_loop()
        self._started = True
        self._stopping = False
        self._lost = asyncio.Event()
        self._subscribe(self._on_receive, self._topic)
        self._subscribe(self._on_lost, self._lost_topic)
        self._subscribed = True
        try:
            self._iface = self._factory()
        except Exception:
            _log.warning("meshtastic initial connect failed", transport=self.name)
            if not self._reconnect:
                self._teardown_subs()
                self._started = False
                raise
            self._iface = None
        self._apply_mesh()
        self._task = asyncio.create_task(self._supervise())

    def _apply_mesh(self) -> None:
        """Apply mesh device config to the current interface, if both present.

        Called on the initial connect and after every supervisor reconnect, so a
        rebuilt interface is re-provisioned rather than reverting to its boot config.
        """
        if self._iface is not None and self._mesh:
            self._provision(self._iface, self._mesh)

    def _on_lost(self, *args: Any, **kwargs: Any) -> None:
        if self._loop is not None and self._lost is not None:
            self._loop.call_soon_threadsafe(self._lost.set)

    async def _supervise(self) -> None:
        backoff = self._backoff_initial
        assert self._lost is not None
        while not self._stopping:
            if self._iface is None:
                try:
                    self._iface = self._factory()
                except Exception:
                    _log.warning("meshtastic connect failed", transport=self.name)
                    await self._sleep(backoff)
                    backoff = min(backoff * self._backoff_factor, self._backoff_max)
                    continue
                backoff = self._backoff_initial
                self.reconnects += 1
                self._apply_mesh()
            await self._lost.wait()
            self._lost.clear()
            self._close_iface()
            if not self._reconnect:
                break
            await self._sleep(backoff)
            backoff = min(backoff * self._backoff_factor, self._backoff_max)

    def _close_iface(self) -> None:
        iface, self._iface = self._iface, None
        if iface is not None:
            try:
                iface.close()
            except Exception:
                _log.debug("meshtastic close error", transport=self.name)

    def _teardown_subs(self) -> None:
        if self._subscribed:
            self._unsubscribe(self._on_receive, self._topic)
            self._unsubscribe(self._on_lost, self._lost_topic)
            self._subscribed = False

    async def send(self, data: bytes) -> None:
        if not self._started:
            raise RuntimeError("transport not started")
        iface = self._iface
        if iface is None:
            return  # transiently disconnected; best-effort drop
        try:
            iface.sendData(
                data,
                destinationId=self.destination,
                portNum=self.portnum,
                wantAck=self.want_ack,
                channelIndex=self.channel_index,
            )
        except Exception:
            _log.warning("meshtastic send failed; dropping frame", transport=self.name)

    def _on_receive(self, packet: dict[str, Any] | None = None, interface: Any = None) -> None:
        decoded = (packet or {}).get("decoded") or {}
        if decoded.get("portnum") not in (self.portnum, self.portnum_name):
            return
        payload = decoded.get("payload")
        if not payload:
            return
        if self._loop is not None:
            # Route through the shared drop-counting ingest so a full inbox is
            # counted (dropped_inbox_full), not an unhandled QueueFull in the loop.
            self._loop.call_soon_threadsafe(self._ingest_nowait, bytes(payload))

    async def stop(self) -> None:
        self._stopping = True
        if self._lost is not None:
            self._lost.set()  # wake the supervisor if it is waiting
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        self._teardown_subs()
        self._close_iface()
        self._started = False
        await super().stop()


@transport_registry.register("meshtastic")
def _make_meshtastic(name: str = "meshtastic", **options: Any) -> MeshtasticTransport:
    return MeshtasticTransport(name=name, **options)
