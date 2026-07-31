"""Shared fragments for meshsa's self-contained operator pages (``meshsa.ui`` and
``meshsa.scout.station``).

Both pages are served as module-constant HTML (no packaged static files; the tested
aiohttp handlers own all behaviour) and both inject a server-side bearer token into their
``<script>`` scope, so both need the same two defenses, single-sourced here instead of
copied — a copy is exactly how the two pages drifted apart before this module existed:

- **Subresource integrity.** MapLibre GL is loaded from a CDN pinned to an exact version
  with a SRI hash and ``crossorigin`` attribute, so a silently swapped CDN artifact can
  never execute in a scope holding a live credential. For fully offline field use, vendor
  the assets and point a page's own ``<script>``/``<link>`` (and ``map_style_url``) at
  local copies instead of these constants.
- **Script-safe literal embedding.** ``json.dumps`` alone does not escape ``<``/``>``/``&``,
  so a value containing ``</script>`` would terminate the enclosing block and let injected
  markup execute; :func:`js_literal` additionally escapes those three characters to
  ``\\uXXXX`` forms, which are valid JSON and decode to the byte-identical JS value.
"""

from __future__ import annotations

import json
from typing import Any

__all__ = ["MAPLIBRE_CSS_TAG", "MAPLIBRE_JS_TAG", "MAPLIBRE_VERSION", "js_literal"]

#: Exact MapLibre GL version every operator page pins. Bump deliberately, together with
#: both SRI hashes below (regenerate via
#: ``curl -s <url> | openssl dgst -sha384 -binary | openssl base64 -A``
#: against the freshly-fetched unpkg artifact — never hand-edit a hash without
#: re-deriving it from the actual bytes being pinned).
MAPLIBRE_VERSION = "4.7.1"

MAPLIBRE_CSS_TAG = (
    f'<link href="https://unpkg.com/maplibre-gl@{MAPLIBRE_VERSION}/dist/maplibre-gl.css" '
    'rel="stylesheet"\n'
    '  integrity="sha384-MinO0mNliZ3vwppuPOUnGa+iq619pfMhLVUXfC4LHwSCvF9H+6P/KO4Q7qBOYV5V"\n'
    '  crossorigin="anonymous" />'
)
MAPLIBRE_JS_TAG = (
    f'<script src="https://unpkg.com/maplibre-gl@{MAPLIBRE_VERSION}/dist/maplibre-gl.js"\n'
    '  integrity="sha384-SYKAG6cglRMN0RVvhNeBY0r3FYKNOJtznwA0v7B5Vp9tr31xAHsZC0DqkQ/pZDmj"\n'
    '  crossorigin="anonymous"></script>'
)


def js_literal(value: Any) -> str:
    """JSON-encode ``value`` for safe embedding inside a ``<script>`` block.

    ``json.dumps`` does not escape ``<``/``>``/``&``, so a string containing
    ``</script>`` would otherwise close the block and inject markup. The ``\\uXXXX``
    forms are valid JSON, so the decoded JS value is byte-identical.
    """
    return json.dumps(value).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
