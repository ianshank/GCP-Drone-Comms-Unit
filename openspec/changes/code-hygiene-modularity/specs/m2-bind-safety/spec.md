# Spec Delta: m2-bind-safety

## MODIFIED Requirements

### Requirement: Single Bind-Guard Primitive
`meshsa.netauth.validate_bind` was the sole bind-guard implementation. It moves to
`meshsa_core.netauth.validate_bind`; `meshsa.netauth` becomes a delegating re-export module
(no `def validate_bind` of its own) and remains a valid import path for every existing caller.
The `bind-guard` CI check's canonical module updates to `meshsa_core.netauth` accordingly. The
check SHALL still fail when a scanned file creates a network listener without importing and
calling `validate_bind` (through either module) and without a declared exception, or when a
`def validate_bind` outside the canonical module does not demonstrably delegate to it.

#### Scenario: Per-service adapter imports through the old path
- **WHEN** a service module (e.g. `ui/app.py`) defines `def validate_bind(...)` whose body
  imports `validate_bind` from `meshsa.netauth` under an alias and calls it
- **THEN** the guard resolves the re-export chain to the canonical `meshsa_core.netauth`
  symbol and passes the file as a delegating adapter

#### Scenario: A definition appears in the shim module itself
- **WHEN** `meshsa/netauth.py` contains anything other than re-export statements (e.g. a
  competing `def validate_bind`)
- **THEN** the guard fails, naming the file and the single-primitive-rule violation

## ADDED Requirements

### Requirement: Authenticated JSON Responses Are Non-Cacheable
Every route that requires a bearer credential and returns JSON SHALL include
`Cache-Control: no-store` on its response, so an intermediary proxy cannot persist an
authorized payload for replay to an unauthenticated client.

#### Scenario: Authenticated JSON route response
- **WHEN** a bearer-guarded route (e.g. `/api/tracks`, `/api/detections`, `/api/health` on any
  of the four `aiohttp` app factories) responds successfully
- **THEN** the response includes `Cache-Control: no-store`

### Requirement: Subresource Integrity on Operator Pages
Every operator-facing HTML page that loads third-party JavaScript or CSS from a CDN SHALL pin
the asset to an exact version with a Subresource Integrity hash and `crossorigin` attribute,
and SHALL escape any server-injected value so it cannot terminate its enclosing `<script>`
context.

#### Scenario: Scout station page loads MapLibre
- **WHEN** `scout/station/_html.py` renders its page
- **THEN** the MapLibre `<link>`/`<script>` tags carry a pinned version and an `integrity`
  attribute matching `ui/_html.py`'s existing pattern, and the injected bearer token is
  escaped through the shared `_js_literal` helper rather than bare `json.dumps`

### Requirement: One Canonical Primitives Package, No Framework Dependency
Primitives shared between `meshsa` and `jetson_yolo_gcs` (clock, registry, structured
logging setup, heartbeat gating, bind-guard auth, MAVLink connection-factory glue) SHALL live
in exactly one place — the `meshsa-core` distribution — which itself SHALL import nothing from
either consumer, so it can never become the far end of the cycle it is meant to prevent.

#### Scenario: Importing meshsa-core does not pull in meshsa
- **WHEN** every module in `meshsa_core` is imported
- **THEN** `"meshsa"` and `"jetson_yolo_gcs"` are absent from `sys.modules` afterward
