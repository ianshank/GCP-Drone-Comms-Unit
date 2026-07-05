"""Self-contained MapLibre operator page (served at ``/``).

Kept as a module constant (data, not logic) so it needs no packaged static files and the
tested aiohttp handlers own all behaviour. MapLibre GL is loaded from a CDN; for fully
offline field use, vendor the asset and point the ``<script>``/``<link>`` at a local copy.
"""

from __future__ import annotations

MAP_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>meshsa scout</title>
<link href="https://unpkg.com/maplibre-gl@4/dist/maplibre-gl.css" rel="stylesheet" />
<script src="https://unpkg.com/maplibre-gl@4/dist/maplibre-gl.js"></script>
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

async function refresh() {
  const res = await fetch('detections');
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
      document.getElementById('info').innerHTML =
        `<b>${p.cls}</b> (${(+p.conf).toFixed(2)})<br/>id ${p.id}<br/>` +
        ['tagged','rejected','inspected'].map(s =>
          `<button onclick="setStatus('${s}')">${s}</button>`).join('');
    });
  }
  if (fc.features.length && map.getZoom() < 10) {
    const f = fc.features[0].geometry.coordinates; map.jumpTo({ center: f, zoom: 17 });
  }
}
async function setStatus(status) {
  if (!selected) return;
  await fetch(`detections/${selected}/status`, { method: 'POST',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status }) });
  refresh();
}
window.setStatus = setStatus;
map.on('load', () => { refresh(); setInterval(refresh, 3000); });
</script>
</body>
</html>
"""
