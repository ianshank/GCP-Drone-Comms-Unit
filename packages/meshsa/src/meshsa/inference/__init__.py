"""Nemotron Ultra Inference Layer.

Provides AI-driven analysis of situational-awareness messages by bridging
the mesh network to NVIDIA's OpenAI-compatible NIM API.

Split into a package (code-hygiene-modularity T-4.1b): ``errors.py`` (the
neutral error taxonomy), ``transport.py`` (the HTTP seam + the only
socket-bound ``# pragma: no cover`` glue), ``client.py`` (pure
retry/backoff/parse logic), ``service.py`` (the stateful pub/sub service +
its ``_RateGate``/``_OfflineQueue`` collaborators), ``config.py``
(``NemotronConfig``). This module re-exports the full prior public surface
(mirrors the ``command/__init__.py`` facade convention) so every existing
import path keeps resolving.

``aiohttp`` is an *optional* dependency — install ``meshsa[inference]`` to enable
the default transport. Inject a custom ``HttpTransport`` and the module works
with no ``aiohttp`` installed at all (the base install is unaffected).
"""

from __future__ import annotations

from .client import InferenceResult, NemotronClient
from .config import NemotronConfig
from .errors import InferenceError, InferenceHttpError, InferenceTransportError
from .service import InferenceService
from .transport import AiohttpTransport, HttpResponse, HttpTransport

__all__ = [
    "AiohttpTransport",
    "HttpResponse",
    "HttpTransport",
    "InferenceError",
    "InferenceHttpError",
    "InferenceResult",
    "InferenceService",
    "InferenceTransportError",
    "NemotronClient",
    "NemotronConfig",
]
