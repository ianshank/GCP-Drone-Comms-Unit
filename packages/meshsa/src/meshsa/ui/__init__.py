"""meshsa.ui — local, read-only, fail-closed operator console (docs/specs/operator-ui.md).

The console is a *service*: it registers no transport/codec and edits neither router nor
models; it attaches via the public ``Router.subscribe``/``Node.on_message`` seam
(spec §3). ``aiohttp`` is imported lazily inside the app factory (the ``[ui]`` extra),
so importing this package never requires it.
"""

from __future__ import annotations

from .config import UIConfig
from .logring import LogRing
from .snapshot import SnapshotStore

__all__ = ["UIConfig", "LogRing", "SnapshotStore"]
