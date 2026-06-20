"""meshsa — modular framework for a distributable mesh SA network."""

from .codec import JsonCodec
from .compact import CompactCodec
from .config import MeshConfig, NemotronConfig, NodeConfig, RouterConfig, TransportConfig
from .cot import CotCodec
from .errors import (
    DuplicateRegistrationError,
    IncompatibleSchemaError,
    MeshSAError,
    UnknownComponentError,
)
from .inference import InferenceResult, InferenceService, NemotronClient
from .models import ChatPayload, Envelope, MessageKind, NodeInfo, NodeTier, PliPayload, Position
from .node import Node, build_node
from .protocols import Clock, Codec, IdFactory, SystemClock, Transport, UuidFactory
from .registry import Registry, codec_registry, transport_registry
from .router import Router
from .transports import (
    LoopbackBus,
    LoopbackTransport,
    MeshtasticTransport,
    NullTransport,
    TakMulticastTransport,
    TakTcpTransport,
)
from .version import SCHEMA_VERSION, __version__, is_compatible

__all__ = [
    "__version__",
    "SCHEMA_VERSION",
    "is_compatible",
    "NodeConfig",
    "MeshConfig",
    "RouterConfig",
    "TransportConfig",
    "NemotronConfig",
    "Position",
    "NodeInfo",
    "NodeTier",
    "MessageKind",
    "Envelope",
    "PliPayload",
    "ChatPayload",
    "Transport",
    "Codec",
    "Clock",
    "IdFactory",
    "SystemClock",
    "UuidFactory",
    "Registry",
    "transport_registry",
    "codec_registry",
    "JsonCodec",
    "CotCodec",
    "CompactCodec",
    "Router",
    "Node",
    "build_node",
    "LoopbackBus",
    "LoopbackTransport",
    "NullTransport",
    "MeshtasticTransport",
    "TakTcpTransport",
    "TakMulticastTransport",
    "MeshSAError",
    "IncompatibleSchemaError",
    "UnknownComponentError",
    "DuplicateRegistrationError",
    "InferenceResult",
    "NemotronClient",
    "InferenceService",
]
