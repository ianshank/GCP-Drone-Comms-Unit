"""Node assembly: turns a :class:`NodeConfig` into a runnable node by wiring
transports (via the registry), a codec, and the router together."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog

from .codec import JsonCodec
from .config import NodeConfig
from .inference import InferenceService
from .models import ChatPayload, Envelope, MessageKind, NodeInfo, PliPayload, Position
from .protocols import Clock, Codec, IdFactory, SystemClock, Transport, UuidFactory
from .registry import Registry, codec_registry, transport_registry
from .router import Handler, Router
from .version import SCHEMA_VERSION

_log = structlog.get_logger("meshsa.node")


@dataclass
class Node:
    config: NodeConfig
    router: Router
    info: NodeInfo
    clock: Clock
    id_factory: IdFactory
    inference_service: InferenceService | None = None

    async def start(self) -> None:
        await self.router.start()
        if self.inference_service:
            self.inference_service.start()

    async def stop(self) -> None:
        if self.inference_service:
            await self.inference_service.stop()
        await self.router.stop()

    def on_message(self, handler: Handler) -> None:
        self.router.subscribe(handler)

    def _envelope(self, kind: MessageKind, payload: dict[str, Any]) -> Envelope:
        return Envelope(
            schema_version=SCHEMA_VERSION,
            msg_id=self.id_factory.new_id(),
            ts=self.clock.now(),
            source_uid=self.info.uid,
            kind=kind,
            payload=payload,
        )

    async def publish_position(self, position: Position) -> Envelope:
        env = self._envelope(
            MessageKind.PLI,
            PliPayload(node=self.info, position=position).model_dump(exclude_none=True),
        )
        await self.router.publish(env)
        return env

    async def publish_chat(self, text: str, to: str | None = None) -> Envelope:
        env = self._envelope(MessageKind.CHAT, ChatPayload(text=text, to=to).model_dump())
        await self.router.publish(env)
        return env


def build_node(
    config: NodeConfig,
    *,
    clock: Clock | None = None,
    id_factory: IdFactory | None = None,
    codec: Codec | None = None,
    registry: Registry[Transport] | None = None,
    transport_kwargs: dict[str, dict[str, object]] | None = None,
    codec_instances: dict[str, Codec] | None = None,
) -> Node:
    """Assemble a Node from config. Unknown transport types are skipped (not
    fatal), so a node tolerates configs written for newer/older builds.

    ``codec_instances`` maps a transport name to a pre-configured ``Codec``
    instance, used in preference to registry-by-name creation for that transport
    — so a caller can inject a custom-configured codec without registering it.
    """
    reg = registry if registry is not None else transport_registry
    clock = clock if clock is not None else SystemClock()
    id_factory = id_factory if id_factory is not None else UuidFactory()
    codec = codec if codec is not None else JsonCodec()
    instances = codec_instances or {}
    transports: list[Transport] = []
    codecs: dict[str, Codec] = {}
    for tc in config.transports:
        if not tc.enabled:
            continue
        if not reg.has(tc.type):
            _log.warning("skipping unknown transport type", type=tc.type, name=tc.name)
            continue
        kwargs = dict(tc.options)
        kwargs["name"] = tc.name
        # Apply node-level defaults that the transport can override per-config.
        # setdefault so an explicit per-transport option (or a test override
        # below) always wins. Non-consumers ignore these via **options/**_.
        kwargs.setdefault("queue_maxsize", config.router.queue_maxsize)
        kwargs.setdefault("mesh", config.mesh.model_dump())
        if transport_kwargs and tc.name in transport_kwargs:
            kwargs.update(transport_kwargs[tc.name])
        transports.append(reg.create(tc.type, **kwargs))
        if tc.name in instances:
            codecs[tc.name] = instances[tc.name]
        elif tc.codec is not None:
            codecs[tc.name] = codec_registry.create(tc.codec, **tc.codec_options)

    router = Router(
        transports, codec, clock=clock, id_factory=id_factory, config=config.router, codecs=codecs
    )
    info = NodeInfo(uid=config.uid, callsign=config.callsign, tier=config.tier)

    inference_service = None
    if config.inference.enabled:
        inference_service = InferenceService(
            config=config.inference,
            router=router,
            clock=clock,
            id_factory=id_factory,
            source_uid=info.uid,
        )

    return Node(
        config=config,
        router=router,
        info=info,
        clock=clock,
        id_factory=id_factory,
        inference_service=inference_service,
    )
