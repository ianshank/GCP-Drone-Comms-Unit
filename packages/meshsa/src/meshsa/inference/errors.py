"""Inference-layer error taxonomy: neutral, transport-agnostic failure types.

Split out of the former flat ``inference.py`` (code-hygiene-modularity T-4.1b),
mirroring the per-subpackage ``errors.py`` convention (``command/errors.py``).
"""

from __future__ import annotations

from ..errors import MeshSAError

#: HTTP status that signals upstream rate limiting (retried with backoff).
_HTTP_TOO_MANY_REQUESTS = 429
#: First HTTP status considered a (retryable) server error (5xx).
_HTTP_SERVER_ERROR_FLOOR = 500


class InferenceError(MeshSAError):
    """Base class for inference-layer failures."""


class InferenceTransportError(InferenceError):
    """A transport-level failure (timeout, connection reset) — retryable."""


class InferenceHttpError(InferenceError):
    """A non-success HTTP response that survived the retry budget."""

    def __init__(self, status: int, message: str = "") -> None:
        self.status = status
        super().__init__(message or f"inference HTTP {status}")


def _is_transient_status(status: int) -> bool:
    """True for HTTP statuses worth retrying/queueing: rate-limit (429) or 5xx server errors."""
    return status == _HTTP_TOO_MANY_REQUESTS or status >= _HTTP_SERVER_ERROR_FLOOR


def _is_offline_retryable(exc: InferenceError) -> bool:
    """True when a failure is a connectivity/transient condition worth an offline replay.

    Transport errors (API unreachable) and *transient* HTTP failures (429 / 5xx that already
    exhausted the retry budget) are offline-worthy. A permanent client error (401/400/404) or a
    malformed-payload / max-retries base ``InferenceError`` is **not** — replaying it can never
    succeed, so it must surface fast instead of cycling in the queue forever.
    """
    if isinstance(exc, InferenceTransportError):
        return True
    if isinstance(exc, InferenceHttpError):
        return _is_transient_status(exc.status)
    return False
