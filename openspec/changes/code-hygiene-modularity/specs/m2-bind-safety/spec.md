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

### Requirement: Bearer Refusals Carry a Challenge
Every 401 a bearer-guarded route returns SHALL carry `WWW-Authenticate: Bearer realm="<service>"`
(RFC 7235 §3.1) and `Cache-Control: no-store`, with the fixed body `{"error": "unauthorized"}`
and no partial data. The realm names the service (`meshsa-ui`, `meshsa-scout`, `meshsa-llm`,
`meshsa-metrics`) and nothing else; it is a hint to a client, not a disclosure.

#### Scenario: Refusal from any of the four factories
- **WHEN** a request to a bearer-guarded route (or a `?token=`-gated page) on `ui/app.py`,
  `scout/station/app.py`, `llm/server.py` or `health.py` presents no credential or the wrong one
- **THEN** the response is a 401 whose headers include the service's `WWW-Authenticate`
  challenge and `Cache-Control: no-store`, and whose body is exactly `{"error": "unauthorized"}`

### Requirement: One Refusal Implementation
The 401 response, the bearer check, the `?token=` page gate, the `no-store` policy and the
JSON-body parse live in `meshsa/_web.py` only; a factory SHALL NOT re-implement any of them.
Bind validation is explicitly excluded (the per-service `validate_bind` adapters stay, see the
Single Bind-Guard Primitive requirement).

#### Scenario: A factory inlines its own 401
- **WHEN** an app factory module builds a 401 or checks `Authorization` without `meshsa._web`
- **THEN** review rejects it (there is no mechanical check; `bind_guard` covers binds only)

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
