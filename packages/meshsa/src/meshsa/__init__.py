"""meshsa — modular framework for a distributable mesh SA network."""

from .codec import JsonCodec
from .compact import CompactCodec
from .config import (
    HealthConfig,
    MeshConfig,
    NemotronConfig,
    NodeConfig,
    RouterConfig,
    ScoutConfig,
    TransportConfig,
)
from .cot import CotCodec
from .detection_codec import DetectionCodec
from .errors import (
    DuplicateRegistrationError,
    IncompatibleSchemaError,
    MeshSAError,
    UnknownComponentError,
)
from .health import health_snapshot
from .inference import (
    AiohttpTransport,
    HttpResponse,
    HttpTransport,
    InferenceError,
    InferenceHttpError,
    InferenceResult,
    InferenceService,
    InferenceTransportError,
    NemotronClient,
)
from .metrics import RouterMetrics, render_prometheus
from .models import (
    Attitude,
    ChatPayload,
    Detection,
    Envelope,
    MessageKind,
    NodeInfo,
    NodeTier,
    PliPayload,
    Position,
    Telemetry,
)
from .node import Node, build_node
from .plugins import load_plugins
from .protocols import Clock, Codec, IdFactory, SystemClock, Transport, UuidFactory
from .registry import Registry, codec_registry, transport_registry
from .router import Router
from .telemetry import TelemetryCodec
from .transports import (
    CrsfSourceTransport,
    DetectionIngestTransport,
    LoopbackBus,
    LoopbackTransport,
    MavlinkSourceTransport,
    MeshtasticTransport,
    MspSourceTransport,
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
    "HealthConfig",
    "TransportConfig",
    "NemotronConfig",
    "ScoutConfig",
    "Position",
    "Attitude",
    "Telemetry",
    "Detection",
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
    "TelemetryCodec",
    "DetectionCodec",
    "Router",
    "RouterMetrics",
    "render_prometheus",
    "health_snapshot",
    "Node",
    "build_node",
    "load_plugins",
    "LoopbackBus",
    "LoopbackTransport",
    "NullTransport",
    "CrsfSourceTransport",
    "DetectionIngestTransport",
    "MavlinkSourceTransport",
    "MspSourceTransport",
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
    "HttpTransport",
    "HttpResponse",
    "AiohttpTransport",
    "InferenceError",
    "InferenceTransportError",
    "InferenceHttpError",
]
