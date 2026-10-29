"""Built-in transports (importing registers them)."""

from .base import AbstractTransport
from .crsf_source import CrsfSourceTransport
from .detection_ingest import DetectionIngestTransport
from .loopback import LoopbackBus, LoopbackTransport, NullTransport
from .mavlink_source import MavlinkSourceOptions, MavlinkSourceTransport
from .meshtastic_radio import MeshtasticOptions, MeshtasticTransport
from .msp_source import MspOptions, MspSourceTransport
from .tak import TakTcpOptions, TakTcpTransport
from .tak_multicast import TakMulticastTransport

__all__ = [
    "AbstractTransport",
    "LoopbackBus",
    "LoopbackTransport",
    "NullTransport",
    "CrsfSourceTransport",
    "DetectionIngestTransport",
    "MavlinkSourceOptions",
    "MavlinkSourceTransport",
    "MspOptions",
    "MspSourceTransport",
    "MeshtasticOptions",
    "MeshtasticTransport",
    "TakTcpOptions",
    "TakTcpTransport",
    "TakMulticastTransport",
]
