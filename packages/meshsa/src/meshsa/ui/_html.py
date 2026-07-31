"""Self-contained MapLibre operator console page (served at ``/``; design D-3).

Kept as a module constant (data, not logic) so it needs no packaged static files and the
tested aiohttp handlers own all behaviour — the ``scout.station._html`` pattern. The pinned
MapLibre GL asset tags and the safe-literal helper live in ``meshsa._webpage`` (shared with
``scout.station._html``, which injects a bearer token into the same kind of scope); for
fully offline field use, vendor the assets and point the ``<script>``/``<link>`` (and
``ui.map_style_url``) at local copies.

XSS posture: the token, panel manifest, and page settings are injected as JSON-encoded JS
literals with ``<``/``>``/``&`` additionally escaped to ``\\uXXXX`` (``json.dumps`` alone
would let a ``</script>`` inside a value terminate the script block), and the page builds
DOM nodes with ``textContent``/``createTextNode`` only — no ``innerHTML`` sink anywhere.
"""

from __future__ import annotations

from typing import Any

from .._webpage import MAPLIBRE_CSS_TAG, MAPLIBRE_JS_TAG
from .._webpage import js_literal as _js_literal

__all__ = ["render_page"]


#: Serve-time placeholders, each replaced with a JSON-encoded value.
_TOKEN_PLACEHOLDER = "__UI_TOKEN__"
_MANIFEST_PLACEHOLDER = "__UI_MANIFEST__"
_SETTINGS_PLACEHOLDER = "__UI_SETTINGS__"
_TITLE_PLACEHOLDER = "__UI_TITLE__"

#: Build-time placeholders for the shared, version-pinned MapLibre asset tags — resolved
#: once below, not per request (design D-3's "single-sourced tags" dedup).
_MAPLIBRE_CSS_PLACEHOLDER = "__MAPLIBRE_CSS_TAG__"
_MAPLIBRE_JS_PLACEHOLDER = "__MAPLIBRE_JS_TAG__"


def render_page(
    token: str | None,
    manifest: list[str],
    *,
    poll_interval_s: float,
    map_style_url: str,
    title: str,
) -> str:
    """Return the console page with token, panel manifest, and settings injected.

    ``/`` itself is gated on the same token by the app (a ``?token=`` query, because
    browsers cannot set an ``Authorization`` header on navigation), so serving the token
    here does not widen exposure — it lets the page's ``fetch`` calls authenticate.
    """
    settings: dict[str, Any] = {
        "poll_interval_ms": int(poll_interval_s * 1000),
        "map_style_url": map_style_url,
    }
    return (
        PAGE_HTML.replace(_TOKEN_PLACEHOLDER, _js_literal(token))
        .replace(_MANIFEST_PLACEHOLDER, _js_literal(manifest))
        .replace(_SETTINGS_PLACEHOLDER, _js_literal(settings))
        .replace(_TITLE_PLACEHOLDER, _js_literal(title))
    )


_PAGE_HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>meshsa operator</title>
__MAPLIBRE_CSS_TAG__
__MAPLIBRE_JS_TAG__
<style>
  body { margin: 0; font-family: system-ui, sans-serif; }
  #map { position: absolute; inset: 0; }
  .panel { position: absolute; z-index: 1; background: rgba(255,255,255,.95);
    padding: 8px 10px; border-radius: 6px; box-shadow: 0 1px 4px rgba(0,0,0,.3);
    font-size: 13px; max-width: 320px; max-height: 45vh; overflow: auto; }
  #status  { top: 8px; left: 8px; }
  #side    { top: 8px; right: 8px; display: flex; flex-direction: column; gap: 8px;
             background: none; box-shadow: none; padding: 0; }
  #side > div { background: rgba(255,255,255,.95); padding: 8px 10px; border-radius: 6px;
             box-shadow: 0 1px 4px rgba(0,0,0,.3); }
  #logs    { bottom: 8px; left: 8px; right: 8px; max-width: none; max-height: 26vh;
             font-family: ui-monospace, monospace; font-size: 11px; }
  #chatlog { max-height: 20vh; overflow: auto; }
  input[type=text] { width: 100%; box-sizing: border-box; }
  h4 { margin: 0 0 4px; font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }
  .muted { color: #666; }
</style>
</head>
<body>
<div id="map"></div>
<div id="status" class="panel"><h4 id="title"></h4><div id="statusbody" class="muted">connecting\u2026</div></div>
<div id="side" class="panel"></div>
<div id="logs" class="panel" hidden><h4>Log tail</h4><div id="logbody"></div></div>
<script>
// Injected by the server (render_page): JSON-encoded literals, never markup.
const UI_TOKEN = __UI_TOKEN__;
const UI_PANELS = __UI_MANIFEST__;
const UI_SETTINGS = __UI_SETTINGS__;
const UI_TITLE = __UI_TITLE__;

document.title = UI_TITLE;
document.getElementById('title').textContent = UI_TITLE;

function authHeaders(extra) {
  const h = extra || {};
  if (UI_TOKEN) { h['Authorization'] = 'Bearer ' + UI_TOKEN; }
  return h;
}
async function getJson(path) {
  const res = await fetch(path, { headers: authHeaders() });
  if (!res.ok) { throw new Error(path + ' -> ' + res.status); }
  return res.json();
}
function setLines(el, lines) {
  el.replaceChildren();
  lines.forEach((line) => {
    const div = document.createElement('div');
    div.textContent = line;   // textContent only: feed data can never become HTML
    el.append(div);
  });
}

const map = new maplibregl.Map({
  container: 'map', style: UI_SETTINGS.map_style_url, center: [0, 0], zoom: 2,
});
let centered = false;
function upsertLayer(id, fc, color) {
  if (map.getSource(id)) { map.getSource(id).setData(fc); }
  else {
    map.addSource(id, { type: 'geojson', data: fc });
    map.addLayer({ id, type: 'circle', source: id, paint: {
      'circle-radius': 6, 'circle-color': color,
      'circle-stroke-width': 1, 'circle-stroke-color': '#fff' } });
  }
  if (!centered && fc.features.length) {
    centered = true;
    map.jumpTo({ center: fc.features[0].geometry.coordinates, zoom: 13 });
  }
}

const side = document.getElementById('side');
function sidePanel(name, heading) {
  const box = document.createElement('div');
  const h = document.createElement('h4'); h.textContent = heading;
  const body = document.createElement('div'); body.id = name + 'body'; body.className = 'muted';
  body.textContent = '\u2026';
  box.append(h, body); side.append(box);
  return body;
}
const panelBodies = {};
if (UI_PANELS.includes('fpv'))  { panelBodies.fpv = sidePanel('fpv', 'FPV link'); }
if (UI_PANELS.includes('chat')) {
  const box = document.createElement('div');
  const h = document.createElement('h4'); h.textContent = 'Assistant';
  const log = document.createElement('div'); log.id = 'chatlog';
  const input = document.createElement('input');
  input.type = 'text'; input.placeholder = 'ask about the picture\u2026';
  input.addEventListener('keydown', async (e) => {
    if (e.key !== 'Enter' || !input.value.trim()) { return; }
    const prompt = input.value.trim(); input.value = '';
    const you = document.createElement('div'); you.textContent = '> ' + prompt; log.append(you);
    try {
      const res = await fetch('api/chat', { method: 'POST',
        headers: authHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({ prompt }) });
      const body = await res.json();
      const reply = document.createElement('div');
      reply.textContent = res.ok ? body.reply : (body.error || 'error');
      log.append(reply);
    } catch (err) {
      const reply = document.createElement('div'); reply.textContent = 'request failed'; log.append(reply);
    }
    log.scrollTop = log.scrollHeight;
  });
  box.append(h, log, input); side.append(box);
}

function flatLines(obj, prefix) {
  const lines = [];
  Object.entries(obj || {}).forEach(([k, v]) => {
    if (v !== null && typeof v === 'object') { lines.push(...flatLines(v, prefix + k + '.')); }
    else { lines.push(prefix + k + ': ' + v); }
  });
  return lines;
}

async function refresh() {
  try {
    const tracks = await getJson('api/tracks');
    upsertLayer('tracks', tracks, '#3182bd');
    const dets = await getJson('api/detections');
    upsertLayer('detections', dets, '#e6550d');
    const health = await getJson('api/health');
    setLines(document.getElementById('statusbody'),
      flatLines(health, '').slice(0, 24));
    if (panelBodies.fpv) {
      const fpv = await getJson('api/fpv');
      setLines(panelBodies.fpv, flatLines(fpv, ''));
    }
    if (UI_PANELS.includes('logs')) {
      const logs = await getJson('api/logs');
      const el = document.getElementById('logs'); el.hidden = false;
      setLines(document.getElementById('logbody'),
        logs.entries.map((e) => `${e.ts.toFixed ? e.ts.toFixed(1) : e.ts} [${e.level}] ${e.event}`));
    }
  } catch (err) {
    document.getElementById('statusbody').textContent = 'refresh failed: ' + err.message;
  }
}
map.on('load', () => { refresh(); setInterval(refresh, UI_SETTINGS.poll_interval_ms); });
</script>
</body>
</html>
"""

#: The final page template with the shared, version-pinned MapLibre tags resolved in —
#: single-sourced from ``meshsa._webpage`` so this page and ``scout.station._html`` can
#: never drift on which CDN version or SRI hash they pin.
PAGE_HTML = _PAGE_HTML_TEMPLATE.replace(_MAPLIBRE_CSS_PLACEHOLDER, MAPLIBRE_CSS_TAG).replace(
    _MAPLIBRE_JS_PLACEHOLDER, MAPLIBRE_JS_TAG
)
