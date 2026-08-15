"""UDP listener source transport for object-detection frames (the DeepStream seam).

DeepStream/YOLO runs in a *separate* process (its own GLib loop); this transport is the
clean network seam between it and the asyncio meshsa node. It binds a loopback UDP port,
receives one JSON detection frame per datagram, and ingests it for the router — where the
``detection`` codec maps it to a MARKER Envelope and the ``cot`` codec emits a TAK marker.

Receive-only (like ``mavlink_source``/``msp_source``): ``send`` is a no-op. It uses an
asyncio datagram endpoint, so ``datagram_received`` runs on the loop thread and can call
``_ingest_nowait`` directly (no cross-thread hand-off).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import structlog

from ..defaults import DEFAULT_LOOPBACK_HOST, DEFAULT_QUEUE_MAXSIZE, PORT_DETECTION_INGEST
from ..netauth import is_loopback, validate_bind
from ..registry import transport_registry
from .base import AbstractTransport

_log = structlog.get_logger("meshsa.transport.detection_ingest")


class _DetectionDatagramProtocol(asyncio.DatagramProtocol):
    def __init__(self, ingest: Callable[[bytes], None]) -> None:
        self._ingest = ingest

    def datagram_received(self, data: bytes, addr: tuple[str | Any, int]) -> None:
        # Never let an ingest error propagate to the event loop (which could tear down the
        # UDP endpoint and stop reception). _ingest_nowait already drops on a full queue;
        # this guards any other unexpected failure so the receiver stays up.
        try:
            self._ingest(data)
        except Exception:
            _log.warning("failed to ingest detection datagram", addr=addr, exc_info=True)


class DetectionIngestTransport(AbstractTransport):
    """Receive-only source that ingests detection JSON datagrams from the detector process."""

    def __init__(
        self,
        name: str = "detections",
        *,
        host: str = DEFAULT_LOOPBACK_HOST,
        port: int = PORT_DETECTION_INGEST,
        queue_maxsize: int = DEFAULT_QUEUE_MAXSIZE,
        token: str | None = None,
        **_options: Any,
    ) -> None:
        super().__init__(name, queue_maxsize)
        # Fail closed at wiring time (AUDIT_M2_AUTH surface #10): a non-loopback bind
        # without a token previously slipped through silently on operator override.
        validate_bind(
            host,
            token,
            service="the detection ingest transport",
            remedy="set a 'token' in the transport options, or bind to 127.0.0.1",
        )
        self._host = host
        self._token = token
        self._port = int(port)
        self._endpoint: asyncio.DatagramTransport | None = None
        #: Actual bound UDP port (resolved after start; useful when port=0 picks one).
        self.bound_port: int | None = None

    async def start(self) -> None:
        await super().start()
        loop = asyncio.get_running_loop()
        endpoint, _protocol = await loop.create_datagram_endpoint(
            lambda: _DetectionDatagramProtocol(self._ingest_nowait),
            local_addr=(self._host, self._port),
        )
        self._endpoint = endpoint
        sock = endpoint.get_extra_info("socket")
        self.bound_port = sock.getsockname()[1] if sock is not None else self._port
        if not is_loopback(self._host):
            # Plain UDP has nowhere to present the token, so until the
            # TransportAuthPolicy signing seam gains an implementation the token only
            # gates the *bind* decision — be loud that payloads are unauthenticated.
            _log.warning(
                "detection ingest bound non-loopback; datagrams are not authenticated "
                "(token gates the bind only until datagram signing lands)",
                host=self._host,
                port=self.bound_port,
            )
        _log.info("detection ingest listening", host=self._host, port=self.bound_port)

    async def stop(self) -> None:
        await super().stop()
        if self._endpoint is not None:
            self._endpoint.close()
            self._endpoint = None

    async def send(self, data: bytes) -> None:
        # Receive-only source: nothing to transmit back toward the detector.
        return None


@transport_registry.register("detection_ingest")
def _make_detection_ingest(name: str = "detections", **options: Any) -> DetectionIngestTransport:
    return DetectionIngestTransport(name=name, **options)
