"""Self-contained MapLibre operator page (served at ``/``).

Kept as a module constant (data, not logic) so it needs no packaged static files and the
tested aiohttp handlers own all behaviour. The pinned MapLibre GL asset tags and the
safe-literal helper live in ``meshsa._webpage`` (shared with ``ui._html``, which injects a
bearer token into the same kind of scope) — this page injects the same kind of credential
and needs the same defenses: an exact CDN version with a Subresource Integrity hash, and
``<``/``>``/``&`` escaped so a token value containing ``</script>`` cannot terminate the
block. For fully offline field use, vendor the assets and point the
``<script>``/``<link>`` at a local copy.
"""

from __future__ import annotations

from ..._webpage import MAPLIBRE_CSS_TAG, MAPLIBRE_JS_TAG
from ..._webpage import js_literal as _js_literal

#: Placeholder replaced at serve time with the JSON-encoded bearer token (or ``null``).
_TOKEN_PLACEHOLDER = "__SCOUT_TOKEN__"

#: Build-time placeholders for the shared, version-pinned MapLibre asset tags — resolved
#: once below, not per request.
_MAPLIBRE_CSS_PLACEHOLDER = "__MAPLIBRE_CSS_TAG__"
_MAPLIBRE_JS_PLACEHOLDER = "__MAPLIBRE_JS_TAG__"


def render_page(token: str | None) -> str:
    """Return the operator page with the bearer token injected for its `fetch` calls.

    The token is embedded via :func:`meshsa._webpage.js_literal` (JSON-encoded and with
    ``<``/``>``/``&`` escaped, so it is a valid JS literal that cannot break out of the
    ``<script>`` block), letting the page attach ``Authorization: Bearer <token>`` to the
    data/status requests. `/` itself is gated on the same token by the app, so serving it
    here does not widen exposure.
    """
    return MAP_HTML.replace(_TOKEN_PLACEHOLDER, _js_literal(token))


_MAP_HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>meshsa scout</title>
__MAPLIBRE_CSS_TAG__
__MAPLIBRE_JS_TAG__
<style>
  body { margin: 0; font-family: system-ui, sans-serif; }
  #map { position: absolute; inset: 0; }
  #panel { position: absolute; top: 8px; right: 8px; z-index: 1; background: #fff;
    padding: 8px 10px; border-radius: 6px; box-shadow: 0 1px 4px rgba(0,0,0,.3);
    max-width: 260px; font-size: 13px; }
  button { margin-right: 4px; }
</style>
</head>
<body>
<div id="map"></div>
<div id="panel"><b>Scout</b><div id="info">click a pin</div></div>
<script>
const map = new maplibregl.Map({
  container: 'map',
  style: { version: 8, sources: {
      osm: { type: 'raster', tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
             tileSize: 256, attribution: '\\u00a9 OpenStreetMap' } },
    layers: [{ id: 'osm', type: 'raster', source: 'osm' }] },
  center: [0, 0], zoom: 2,
});
const COLORS = { new: '#e6550d', tagged: '#31a354', rejected: '#636363', inspected: '#3182bd' };
let selected = null;
// Injected by the server (render_page): the bearer token for a secured deployment, or null.
const SCOUT_TOKEN = __SCOUT_TOKEN__;
function authHeaders(extra) {
  const h = extra || {};
  if (SCOUT_TOKEN) { h['Authorization'] = 'Bearer ' + SCOUT_TOKEN; }
  return h;
}

async function refresh() {
  const res = await fetch('detections', { headers: authHeaders() });
  if (!res.ok) { document.getElementById('info').textContent = 'auth required'; return; }
  const fc = await res.json();
  if (map.getSource('dets')) { map.getSource('dets').setData(fc); }
  else {
    map.addSource('dets', { type: 'geojson', data: fc });
    map.addLayer({ id: 'dets', type: 'circle', source: 'dets', paint: {
      'circle-radius': 6,
      'circle-color': ['match', ['get', 'status'],
        'tagged', COLORS.tagged, 'rejected', COLORS.rejected, 'inspected', COLORS.inspected,
        COLORS.new],
      'circle-stroke-width': 1, 'circle-stroke-color': '#fff' } });
    map.on('click', 'dets', (e) => {
      const p = e.features[0].properties; selected = p.id;
      // Build the panel with DOM nodes + textContent (never innerHTML) so class/id strings
      // from feature properties can never be interpreted as HTML — no XSS sink.
      const info = document.getElementById('info');
      info.replaceChildren();
      const title = document.createElement('b'); title.textContent = p.cls;
      info.append(title, document.createTextNode(` (${(+p.conf).toFixed(2)})`),
        document.createElement('br'), document.createTextNode('id ' + p.id),
        document.createElement('br'));
      ['tagged','rejected','inspected'].forEach(s => {
        const btn = document.createElement('button');
        btn.textContent = s;
        btn.addEventListener('click', () => setStatus(s));
        info.append(btn);
      });
    });
  }
  if (fc.features.length && map.getZoom() < 10) {
    const f = fc.features[0].geometry.coordinates; map.jumpTo({ center: f, zoom: 17 });
  }
}
async function setStatus(status) {
  if (!selected) return;
  await fetch(`detections/${selected}/status`, { method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }), body: JSON.stringify({ status }) });
  refresh();
}
window.setStatus = setStatus;
map.on('load', () => { refresh(); setInterval(refresh, 3000); });
</script>
</body>
</html>
"""

#: The final page template with the shared, version-pinned MapLibre tags resolved in —
#: single-sourced from ``meshsa._webpage`` so this page and ``ui._html`` can never drift
#: on which CDN version or SRI hash they pin (the gap this module previously had).
MAP_HTML = _MAP_HTML_TEMPLATE.replace(_MAPLIBRE_CSS_PLACEHOLDER, MAPLIBRE_CSS_TAG).replace(
    _MAPLIBRE_JS_PLACEHOLDER, MAPLIBRE_JS_TAG
)
