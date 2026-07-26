# Operator UI — local, read-only, fail-closed console for the MeshSA edge node

> **Status: Implemented** (fakes-first; field validation pending — §8 exit criteria).
> (Definition → Implemented → Validated; see
> [README.md](README.md).) Pairs with [../CHARTER.md](../CHARTER.md) (scope + invariants),
> [../ROADMAP.md](../ROADMAP.md) (M4 "health/observability dashboards"), and
> [../IMPLEMENTATION_PLAN.md](../IMPLEMENTATION_PLAN.md) (Track F).
> Change deliberately; code docstrings cite this spec's `§` numbers.
> **Sequencing:** proposed while M2 was open and ratified via
> `openspec/changes/meshsa-operator-ui/proposal.md` (CHARTER §6 convention); the
> implementation ships as `meshsa.ui` behind the `[ui]` extra.

**Milestone / Initiative:** M4 (Fleet & resilience) — observability surface
**Track:** F.3 (new row; F.1/F.2 are the existing M4/M5 planned specs)
**Author:** rev.2 of a peer-reviewed operator draft
(`docs/OPENSPEC_OPERATOR_UI_PEER_REVIEW.md`), 2026-07-26

---

## 1. Scope

Deliverables (priority order):

1. **`meshsa.ui` subpackage** (extra `ui = ["aiohttp>=3.9"]`, console script `meshsa-ui`)
   serving a fail-closed, single-page operator console; `enabled=false`, loopback, no token
   by default — zero new default-on surface.
2. **`SnapshotStore`** — a router-subscriber that maintains the *current tactical picture*
   (PLI tracks keyed by `source_uid`; MARKER detections keyed by `(source_uid,
   detection.track_id)`, `msg_id` fallback), bounded and
   TTL-evicted, rendered to GeoJSON `FeatureCollection`s by pure helpers. **This store is new
   code: no current-tracks snapshot exists anywhere in `meshsa` today** (the router is a
   stateless pump/bridge) — it is the load-bearing deliverable of this spec.
3. **Single-page MapLibre console** (module-constant HTML, scout-station pattern): live map
   (tracks + detections), health/metrics panel, FPV link-health strip (optional), read-only
   chat pane (optional), log tail (optional). Panels degrade by omission when their source is
   absent.
4. **Auth identical to the scout station:** bearer token on data endpoints, `?token=` gating
   for the page, `/healthz` open, 401 JSON with no partial data.
5. **`UIConfig`** on `NodeConfig` with a complete `MESHSA_UI_*` env map (§5.1); example
   systemd unit + env file under `flightctl/systemd/`.
6. **Governance artifacts:** a new `docs/AUDIT_M2_AUTH.md` surface row, a
   `.claude/governance.yaml` bind-guard exception for the serve loop (scout `cli.py`
   precedent), and registration in `docs/specs/README.md`.

### Non-goals (explicitly deferred)

- **Any command / RC / mission / arm surface.** CHARTER §3's read-only posture holds; the
  Initiative-C gate (`c_gate_met: false`) is untouched. A future mutating endpoint requires
  its own spec and ratification.
- **Replacing ATAK or QGroundControl** — this is the node-local triage/ops pane.
- **Server-Sent Events / WebSockets.** No SSE precedent exists in the tree; short-polling is
  normative (§4). Revisit only with a measured need.
- **Detection triage mutations** — the scout station keeps that role (`POST
  /detections/{id}/status` stays there).
- **Offline map tiles** — the style URL is a config field; vendoring the MapLibre assets for
  fully offline field use is documented, not shipped.
- **PWA / native app** — the page must render on a phone browser; nothing more in v1.
- **TLS termination, log shipping/persistence, multi-node fleet view** (fleet view belongs to
  the M4 federation spec, whose module globs stay frozen during M2).

---

## 2. Facts the implementation relies on

Each fact is cited to the tree (commit `24ddac3`); anything that varies in the field is a §5
config field, not a literal.

- **Envelope + kinds.** Every transport carries `Envelope{schema_version, msg_id, ts,
  source_uid, kind, payload}` (`models.py:168`); `MessageKind` is `PLI | CHAT | MARKER |
  STATUS` (`models.py:25`). Telemetry stamps `kind=PLI` (`telemetry.py:118`); detections are
  `kind=MARKER` with a `detection` block (`detection_codec.py` module docstring) whose
  `track_id` is per-source tracker numbering and nullable (`models.py:133`).
- **Subscription seam.** `Router.subscribe(handler)` delivers every inbound envelope after
  dedupe (`router.py:65`); `Node.on_message` re-exposes it. **No component in the tree retains
  a current-state snapshot** — the router pumps and forwards only.
- **Auth primitives.** `meshsa.netauth` is the single permitted bind/auth module:
  `is_loopback` (l.18), `authorize` (l.23), and `validate_bind(host, token, *, service,
  remedy)` (l.41, keyword-only). Entry points define *delegating adapters* naming their
  service + operator remedy (`scout/station/app.py:35`, `llm/server.py:103`); the
  `bind_guard.py` CI job fails any listener file that neither import-and-calls the canonical
  symbol nor carries a `.claude/governance.yaml` exception (`scout/cli.py` shows the
  serve-loop exception pattern).
- **Health/metrics reuse.** `health_snapshot(node)` (health.py:72) and
  `render_metrics(node, fmt)` (health.py:89) are in-process callables; `/metrics` discloses
  counters and is bearer-gated in its own listener (`build_healthz_app`, health.py:115).
- **FPV reuse.** `LinkHealthMonitor.evaluate() -> HealthReport`
  (`fpv/link_health.py:86,111`); the `fpv` extra pulls `pyserial`/`pyarrow`, so the FPV panel
  must degrade by omission when the extra is absent.
- **LLM reuse.** The llm agent seam (`chat_reply(agent, payload, ...)`, `llm/server.py`) is
  framework-pure; its error policy — generic 502 to the browser, detail logged server-side —
  is the precedent this console inherits.
- **Page pattern.** House pages are module-constant HTML served by tested handlers, "no
  packaged static files" (`scout/station/_html.py`, llm `CHAT_WIDGET_HTML`); MapLibre GL is
  loaded from the unpkg CDN with an explicit vendoring note for offline use.
- **Config pattern.** `NodeConfig.from_env` (config.py:197) resolves `MESHSA_*` env vars into
  nested sub-configs via explicit per-field maps (`HealthConfig` config.py:122, `ScoutConfig`
  config.py:140 are the table precedents).
- **Port inventory** (`docs/AUDIT_M2_AUTH.md`): 8087/8089 TAK, 6969 TAK multicast, 8088
  healthz, 8090 llm, 8095 commander, 8099 scout station **and** detection-ingest UDP (a known
  double-booking flagged in NEXTSTEPS). **8100 is unclaimed** → default `MESHSA_UI_PORT`.
- **Enforced gates.** `--cov-fail-under=97` package-wide (`packages/meshsa/pyproject.toml:106`);
  `ruff` (`E,F,I,UP,B,SIM`), `ruff format`, `mypy --strict`.
- **Forward compatibility.** M3 richer-track fields arrive as *additive optional* payload keys
  (`Position.course_deg/speed_ms` pattern, `models.py`); the snapshot must pass unknown scalar
  keys through rather than dropping them.

---

## 3. Architecture

```text
                    ┌──────────────────────────────────────────────┐
 Router ──subscribe─► SnapshotStore (bounded, TTL; PLI + MARKER)   │
                    │        │ tracks_geojson() / detections_geojson()   (pure)
                    │        ▼                                     │
 Browser ──HTTP────► build_ui_app(sources, *, host, token)  [aiohttp]
   ?token= gate     │   /                → module-constant page (MapLibre + panels)
   Bearer on /api   │   /healthz         → open liveness (house norm)
                    │   /api/tracks      → SnapshotStore GeoJSON
                    │   /api/detections  → SnapshotStore GeoJSON
                    │   /api/health      → health_snapshot + render_metrics (in-process)
                    │   /api/fpv         → FpvSource (optional; omitted when absent)
                    │   /api/chat  POST  → ChatBackend (optional; read-only, no tools)
                    │   /api/logs        → LogRing (optional; bounded)
                    └──────────────────────────────────────────────┘
```

Seams (all injectable `Protocol`s, faked in tests; `UISources` dataclass carries them):

- `SnapshotSource` — `tracks_geojson()` / `detections_geojson()` (implemented by
  `SnapshotStore`; a fake in tests).
- `HealthSource` — wraps `health_snapshot`/`render_metrics` over the running node.
- `FpvSource` (optional) — wraps `LinkHealthMonitor.evaluate()`.
- `ChatBackend` (optional) — wraps the llm agent's `ask`; **exposes no tools that mutate or
  command** (§4).
- `LogSource` (optional) — the bounded structlog ring (§5.4).

Placement: the UI is a **service**, not a transport or codec — it registers nothing in
`transport_registry`/`codec_registry` and edits neither router, node, nor models; it attaches
via the public `subscribe` seam. Stateful I/O (snapshot, ring, HTTP) lives in the service;
GeoJSON/page renderers stay pure. Modules: `ui/config.py`, `ui/snapshot.py`, `ui/logring.py`,
`ui/sources.py`, `ui/app.py`, `ui/_html.py`, `ui/cli.py`.

---

## 4. Behaviour / state model

Normative rules:

- **Fail-closed bind.** `meshsa.ui.app.validate_bind(host, token)` is a delegating adapter
  over `netauth.validate_bind` with `service="meshsa-ui"` and a remedy naming
  `MESHSA_UI_TOKEN` and the disclosure ("the console shows live positions, health, and logs.
  Set a UI token, or bind to 127.0.0.1."). `build_ui_app` enforces it **inside the factory**
  when `host` is given (scout pattern: the guarantee travels with the app). Empty/whitespace
  tokens normalize to `None` at config load (llm `load_config` precedent) — an empty
  credential is no credential.
- **Auth.** When a token is configured: every `/api/*` route requires `Authorization: Bearer`
  (checked via `netauth.authorize`); `/` is gated by `?token=` (browsers cannot set headers on
  navigation) and serves the page with the token JSON-injected for its `fetch` calls
  (XSS-hardened exactly as `_html.py`: JSON-encoded token, `textContent`, no `innerHTML`).
  Mismatch → `401 {"error": "unauthorized"}`, no partial data. `/healthz` stays open
  (liveness; discloses nothing — house norm across llm/scout/healthz).
- **Read-only surface.** All routes are GET except `POST /api/chat`, which answers questions
  and mutates nothing. The `ChatBackend` MUST NOT register command/mutation tools; the
  Initiative-C command path is out of this surface by construction. A route-table test
  asserts the method inventory (§7).
- **Snapshot state.** On each envelope: `PLI` → upsert track by `source_uid`; `MARKER` →
  upsert detection by the composite key `(source_uid, payload.detection.track_id)` —
  `track_id` alone is not globally unique and is nullable (`models.py:133`), so fall back to
  `msg_id` when it is `None`; `CHAT`/`STATUS` →
  ignored in v1. Eviction: entries older than `track_stale_s`/`detection_stale_s` are swept
  **on read** using the injected `Clock` (no background task); caps `max_tracks`/
  `max_detections` evict oldest-first. Unknown scalar payload keys pass through to GeoJSON
  `properties` (M3 additive forward-compat); non-scalar unknowns are dropped, counted, and
  never break rendering.
- **Refresh.** The page short-polls every `poll_interval_s` (client `setInterval`). SSE is a
  non-goal (§1).
- **Degradation.** An absent optional source ⇒ its route is not registered and the page's
  panel manifest omits the panel — no error states for missing extras (fpv-optional
  precedent). A present source that raises ⇒ generic 502 JSON, detail logged server-side
  (llm policy); per-path handling, no blanket catch.
- **Log exposure.** The ring is opt-in (`log_ring_enabled=false`). Entries are structured
  scalars only (ts, level, logger, event, whitelisted scalar bound values). Exposure sits
  behind the same bearer boundary as the data routes; safety rests on the repo-wide
  no-secrets-in-logs discipline (CHARTER §4.7). The ring is in-memory and bounded; it is not
  a log shipper.

---

## 5. Module specifications

> **No magic numbers (CHARTER §4.5).** Every operational value below is a config field with
> an explicit default and env binding, resolved through `NodeConfig.from_env` like
> `HealthConfig`/`ScoutConfig`.

### 5.1 `ui/config.py` — `UIConfig` (nested on `NodeConfig` as `ui:`)

| Field | Type | Default | Env binding | Meaning |
| ----- | ---- | ------- | ----------- | ------- |
| `enabled` | `bool` | `false` | `MESHSA_UI_ENABLED` | Master switch (no listener unless true) |
| `host` | `str` | `"127.0.0.1"` | `MESHSA_UI_HOST` | Bind address (non-loopback requires `token`) |
| `port` | `int` | `8100` | `MESHSA_UI_PORT` | Bind port (free per audit inventory; avoids the 8099 double-booking) |
| `token` | `str \| None` | `None` | `MESHSA_UI_TOKEN` | Bearer token; `""`/whitespace → `None` |
| `map_style_url` | `str` | `"https://demotiles.maplibre.org/style.json"` | `MESHSA_UI_MAP_STYLE_URL` | MapLibre style (point at a local style for offline) |
| `poll_interval_s` | `float` (>0) | `2.0` | `MESHSA_UI_POLL_INTERVAL_S` | Client refresh cadence |
| `track_stale_s` | `float` (>0) | `300.0` | `MESHSA_UI_TRACK_STALE_S` | PLI eviction TTL |
| `detection_stale_s` | `float` (>0) | `3600.0` | `MESHSA_UI_DETECTION_STALE_S` | MARKER eviction TTL (scout's own pins use 86 400 s; live-ops default is deliberately shorter) |
| `max_tracks` | `int` (>0) | `256` | `MESHSA_UI_MAX_TRACKS` | Track cap (oldest evicted) |
| `max_detections` | `int` (>0) | `1024` | `MESHSA_UI_MAX_DETECTIONS` | Detection cap (oldest evicted) |
| `chat_enabled` | `bool` | `false` | `MESHSA_UI_CHAT_ENABLED` | Chat panel (needs `llm` extra + key) |
| `log_ring_enabled` | `bool` | `false` | `MESHSA_UI_LOG_RING_ENABLED` | Log panel + ring processor |
| `log_ring_size` | `int` (>0) | `200` | `MESHSA_UI_LOG_RING_SIZE` | Ring capacity (entries) |
| `log_ring_level` | `str` | `"info"` | `MESHSA_UI_LOG_RING_LEVEL` | Minimum level captured |
| `metrics_format` | `"prometheus" \| "json"` | `"json"` | `MESHSA_UI_METRICS_FORMAT` | `/api/health` metrics render |
| `title` | `str` | `"MeshSA Operator"` | `MESHSA_UI_TITLE` | Page title |

### 5.2 `ui/snapshot.py` — `SnapshotStore`

- `SnapshotStore(clock: Clock, *, max_tracks: int, max_detections: int, track_stale_s: float,
  detection_stale_s: float)`; satisfies `SnapshotSource`.
- `handle(envelope: Envelope) -> None` — the router-subscriber (synchronous state upsert;
  runs on the pump loop; single-event-loop → no locks).
- `tracks_geojson() -> dict` / `detections_geojson() -> dict` — pure renders; sweep stale
  entries via the injected clock before rendering.
- Counters for dropped/evicted entries surface in `/api/health` (observability of the bound).

### 5.3 `ui/app.py` — factory + pure helpers

- `validate_bind(host, token)` — delegating adapter (§4; satisfies the bind-guard rule).
- `build_ui_app(sources: UISources, config: UIConfig, *, host: str | None = None,
  token: str | None = None) -> web.Application` — bind enforced inside when `host` is given;
  registers only routes whose sources exist; `aiohttp` imported inside the factory (health.py
  precedent) so `meshsa` imports clean without the extra.
- Pure helpers unit-tested without aiohttp: `panel_manifest(sources)`,
  `guard(token, header) -> tuple[dict, int] | None` (`None` = allowed, else a
  `(body, 401)` pair the route turns into a JSON response), and the page render
  (`ui/_html.py: render_page(token, manifest, *, poll_interval_s, map_style_url, title)`).

### 5.4 `ui/logring.py` — `LogRing`

- `LogRing(size: int, level: str)`; `.processor` is a structlog processor appended at wiring
  time (opt-in); `.entries() -> list[dict]` returns bounded structured scalars (§4).

### 5.5 `ui/cli.py` — `meshsa-ui` entry point

- Builds `NodeConfig.from_env()`, starts the node, attaches `SnapshotStore`, wires real
  sources, serves via `web.run_app` (the only `# pragma: no cover` glue). The serve loop is
  guarded transitively by `build_ui_app` → requires the `.claude/governance.yaml` bind-guard
  exception with the `scout/cli.py` rationale wording.

---

## 6. Wire / schema posture (backward compatibility)

**N/A — no wire change.** The console is a pure consumer: no new `Envelope`, no
`schema_version` bump, no codec, no emission. It MUST tolerate additive optional payload keys
(M3.1 pattern) by passing unknown scalars through to GeoJSON properties (§4), so richer-track
fields appear on the map without a console change.

---

## 7. Test plan (by category)

Coverage floor: the enforced package gate (`--cov-fail-under=97`) stays green; the bind/auth
adapter, snapshot eviction, and log ring target **100 % per-module** (the documented
`netauth`/`pacing` precedent). Serve-loop wiring is the only `# pragma: no cover`. Fakes
first; no hardware, radios, sockets, or live tiles in CI.

- **Unit** — snapshot upsert/eviction with `FakeClock` (TTL sweep, cap eviction order,
  unknown-key passthrough incl. non-scalar drop+count); GeoJSON builders; `panel_manifest`;
  config parsing (env map, `""`→`None` token, bounds validation); log ring (capacity, level
  floor, scalar-only entries).
- **Integration** — `TestClient` against `build_ui_app` with fakes: 200 happy paths per
  route; 401 without/with-wrong bearer on every `/api/*`; `?token=` page gate (401 without,
  200 with, token JSON-injected); absent sources ⇒ routes absent (404) + manifest omission;
  raising source ⇒ generic 502, detail only in logs.
- **Security** — construction refuses non-loopback bind with `None`/empty token (adapter
  raises with service + remedy text); loopback-no-token allowed; route-table method
  inventory: GET-only except `POST /api/chat`; `ChatBackend` conformance: no tool/command
  attribute surface; no secret material in ring entries given a seeded logger.
- **Property (Hypothesis)** — eviction invariants: store never exceeds caps, never returns an
  entry older than its TTL, upsert idempotent per key under arbitrary envelope interleavings.
- **Golden vectors** — a `FeatureCollection` golden for a PLI+MARKER mix, including an M3
  additive field passing through, with a wrong-decode negative assertion.

---

## 8. Exit criteria

- **Mechanism (binary):** §7 green; `ruff`/`ruff format`/`mypy --strict`/`pytest` green with
  the 97 % gate; 100 % on the three named modules; `docs/AUDIT_M2_AUTH.md` row added (surface
  #17: default off, `127.0.0.1:8100`, bearer, plaintext HTTP, fails closed);
  `.claude/governance.yaml` exception landed; `docs/specs/README.md` row → `Implemented`;
  CHANGELOG + NEXTSTEPS updated; systemd example + env file under `flightctl/systemd/`.
- **Validation (separate):** field smoke on the unit (Jetson Orin / Pi 5) with live radios —
  tracks + detections render and evict; phone-browser check over the LAN with token +
  non-loopback deliberately configured; ring memory bounded over a soak window. Status →
  `Validated` only after these pass (thresholds stay provisional until measured — FPV §8
  split).

---

## 9. CHARTER §4 invariant checklist

| # | Invariant | How this design preserves it |
|---|-----------|------------------------------|
| 1 | Open/closed registry extensibility | The console registers no transport/codec; it attaches via the public `Router.subscribe`/`Node.on_message` seam; router, node, and models are untouched |
| 2 | Versioned, backward-compatible wire | §6 N/A — consumer only; additive unknown keys tolerated, never emitted |
| 3 | DI via `Protocol`, tests need no hardware | `SnapshotSource`/`HealthSource`/`FpvSource`/`ChatBackend`/`LogSource` + `Clock` are injected; suite runs on fakes + `TestClient` |
| 4 | Stateful I/O in transports/services, not codecs | Snapshot, ring, and HTTP live in the `ui` service; codecs untouched; renderers pure |
| 5 | Config-driven, no magic numbers | §5.1 — every cadence, TTL, cap, port, and URL is a field with default + env binding |
| 6 | Quality gates green; hardware glue is the only pragma | 97 % package gate + 100 % on auth/eviction/ring; only the serve loop is pragma'd |
| 7 | No secrets / machine fingerprints in repo | Token via env/runtime only; systemd example ships an `.env.example` placeholder; ring inherits the no-secrets logging discipline |
