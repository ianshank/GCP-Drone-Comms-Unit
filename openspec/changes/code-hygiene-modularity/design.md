# Design — Code Hygiene & Modularity Program

## D-1. `fpv/` carve-out preservation (charter compliance)

The `fpv` audit's dead-code list conflated two things: genuinely unreferenced surface
(`AddressProber`, `fpv/camera.py`, `TelemetryStore.age_s`/`.history`) and surface that
implements the **ratified 2026-06-12 pre-flight arm-gating carve-out** (`CHARTER.md` §3):
`ArmGuard`, `crsf/rc.py`, `CrsfLink.send_rc`, the `RCLink` protocol, `FlightLogger.record_rc`.
The carve-out text is explicit: *"the `meshsa.fpv` ground-side subsystem may transmit RC
frames for the single purpose of a pre-flight safety interlock."* That capability exists in
code, is unit-tested, and is simply not yet wired to a production entry point
(`command/safety.py` reuses only a 3-line predicate, not `ArmGuard` itself, by its own
docstring). Deleting it would retire ratified capability through a hygiene commit — exactly
what `CHARTER.md` §6 reserves for a deliberate human decision.

**Resolution**: split T-5.1 into two commits.
- **5.1a (delete)**: surface with no charter backing and no production or test-fixture
  purpose — `AddressProber`/`ProbeResult`/`ProberSettings`, `fpv/camera.py` +
  `CameraSource`/`Frame` (the jetson package's `streaming/camera.py` copy is live and
  strictly better — it fails fast on an unopenable pipeline and stamps a real monotonic
  timestamp instead of `fpv/camera.py`'s always-overwritten `t=0.0`), `TelemetryStore.age_s`/
  `.history`, `SUPPORTED_DATASET_SCHEMAS`, `crsf/__init__.py`'s unused re-exports,
  `llm/server.py`'s vestigial `MAX_PROMPT_CHARS` alias.
- **5.1b (keep + mark)**: `arm_guard.py`, `crsf/rc.py`, `send_rc`, `RCLink`, `record_rc` get a
  module-level note — *"Implements the ratified 2026-06-12 pre-flight arm-gating carve-out
  (CHARTER.md §3). Not yet wired to a production entry point; retiring this is a §6 decision,
  not a hygiene change."* — plus a `docs/NEXTSTEPS.md` entry surfacing the wire-or-retire
  decision explicitly for a maintainer.

## D-2. `packages/meshsa_core` — shared primitives, not a fork

**Distribution** `meshsa-core`, **import package** `meshsa_core`, at
`packages/meshsa_core/` (`src/meshsa_core/` layout, `py.typed`, own `pyproject.toml`,
own `tests/`). Dependencies: `structlog` only, plus an optional `mavlink` extra for the
`pymavlink`-touching glue. Python `>=3.10` (matches both consumers). Own coverage gate,
`--cov-fail-under=97`.

**Modules**: `errors.py` (`CoreError`, `DuplicateRegistrationError`,
`UnknownComponentError` — used only as injectable defaults, see below), `registry.py`,
`clock.py` (`Clock` protocol, `SystemClock`, `MonotonicClock` — identical in both packages
today), `logging.py` (`configure_logging`, `log_level_num` — jetson's version is a superset
and becomes canonical), `heartbeat.py` (`HeartbeatReport`, `HeartbeatMonitor`), `backoff.py`
(`Backoff`, `SleepFn`, new `BackoffSettings`), `netauth.py` (`is_loopback`, `authorize`,
`validate_bind`, `TransportAuthPolicy`, `NetAuthPolicy`, `DEFAULT_POLICY` — moved verbatim
from `meshsa.netauth`), `mavlink.py` (`resolve_connection`, `extract_endpoint_host`),
`version.py`.

**Registry error-type injection** is the one real design problem: meshsa's registry errors
subclass `MeshSAError` (a `KeyError`/`ValueError` multiple-inheritance hierarchy with test
coverage); jetson's subclass `JetsonYoloError`. Both are public catch surfaces. Resolution:

```python
class Registry(Generic[T]):
    def __init__(
        self, kind: str, *,
        duplicate_error: type[Exception] = DuplicateRegistrationError,
        unknown_error: type[Exception] = UnknownComponentError,
    ) -> None: ...
```

`meshsa.registry.Registry` becomes a thin subclass pinning meshsa's error types (so
`isinstance`/`except MeshSAError` sites are unaffected); jetson's `core/registry.py` mirrors
it with jetson's error types. `UnknownComponentError(MeshSAError, KeyError)`'s
multiple-inheritance stays entirely inside `meshsa/errors.py`, untouched.

**Anti-cycle test**: `meshsa_core` imports only stdlib + `structlog`, never `meshsa` or
`jetson_yolo_gcs`. A test imports every `meshsa_core` module and asserts `"meshsa" not in
sys.modules` afterward.

**Consumer pins**: both packages declare `meshsa-core>=0.1,<0.2`.

## D-3. Re-export shims, not import breaks

Every symbol that moves gets an explicit-alias re-export at its old location — mypy
`--strict`'s `no_implicit_reexport` requires the `as` form:

```python
# meshsa/protocols.py
from meshsa_core.clock import Clock as Clock, SystemClock as SystemClock, MonotonicClock as MonotonicClock
```

`meshsa.protocols.Clock` and `meshsa_core.clock.Clock` are the same object post-move, so
`runtime_checkable`/`isinstance` behavior is unaffected. Same pattern for
`meshsa/transports/backoff.py` (`Backoff`/`SleepFn`/`BackoffSettings`), `meshsa/cli.py`
(`configure_logging` delegates), and jetson's `core/clock.py`, `core/registry.py`,
`core/logging.py`, `mavlink/heartbeat.py`. `meshsa/netauth.py` is the one shim with an
additional constraint — see D-4.

Two visible behavior deltas, both flagged in `CHANGELOG.md`: the adopted logging renderer is
a superset (gains an ISO timestamp + level that meshsa's current renderer doesn't emit), and
the health-service port default changes (D-6).

## D-4. Bind-guard mechanics of the `netauth` move

`tools/claude_hooks/bind_guard.py`'s single-primitive rule (verified at
`bind_guard.py:186-205`) fires on any `def validate_bind` **outside** the canonical module
whose body does not delegate to the canonical symbol. Consequence: `meshsa/netauth.py`
must become a **pure re-export module with no `def validate_bind` of its own** —

```python
# meshsa/netauth.py — canonical home is now meshsa_core.netauth (moved <task>).
from meshsa_core.netauth import DEFAULT_POLICY as DEFAULT_POLICY
from meshsa_core.netauth import NetAuthPolicy as NetAuthPolicy
from meshsa_core.netauth import TransportAuthPolicy as TransportAuthPolicy
from meshsa_core.netauth import authorize as authorize
from meshsa_core.netauth import is_loopback as is_loopback
from meshsa_core.netauth import validate_bind as validate_bind
```

— and `.claude/governance.yaml`'s `bind_guard.canonical_module` flips from `"meshsa.netauth"`
to `"meshsa_core.netauth"` **in the same commit**. The four per-service adapters
(`ui/app.py:46`, `scout/station/app.py:35`, `llm/server.py:103`, `health.py:24`,
`flightctl/run_commander.py:160`) each already `def validate_bind(...)` with a body that
imports and calls the canonical symbol under an aliased name (`_validate_bind`) — the
linter's alias-tracking (`_canonical_aliases`) resolves through re-export chains by module
tail (`netauth`), so these keep passing unmodified against the new canonical module. This
commit's verification runs `python tools/claude_hooks/bind_guard.py` and the governance hook
test suite explicitly, not just the default gate.

**Bind validation is never routed through the new `_web.py` kit** (D-5) — doing so would
require the adapter rule to understand a third module, and the existing per-service
6-line-adapter shape is exactly what the linter is built to recognize.

## D-5. `meshsa/_web.py` — shared aiohttp service kit

```python
@dataclass(frozen=True)
class ServiceAuth:
    service: str          # e.g. "meshsa-ui" — used in the WWW-Authenticate realm
    realm: str
    token: str | None      # already normalized (strip-or-None)

def normalize_token(token: str | None) -> str | None
def unauthorized(auth: ServiceAuth) -> web.Response
    # 401 {"error": "unauthorized"} + WWW-Authenticate: Bearer realm="<realm>" (RFC 7235,
    # house-wide now — today only health.py sends this)
def bearer_guard(auth: ServiceAuth, request: Any) -> web.Response | None   # None == allowed
def page_token_gate(auth: ServiceAuth, request: Any) -> web.Response | None
def api_json(body: Any, *, status: int = 200) -> web.Response
    # web.json_response(...) + Cache-Control: no-store on every authenticated JSON route
def html_page(page: str) -> web.Response         # text/html + no-store
async def read_json_or_none(request: Any) -> Any | None
async def healthz(_request: Any) -> web.Response  # {"status": "ok"}
def upstream_error(log: Any, route: str, exc: Exception, *, message: str) -> web.Response
```

Adopted by `ui/app.py`, `scout/station/app.py`, `llm/server.py`, `health.py`. Migration is
characterization-test-first (D-8): pin every route's status/headers/body across all four
factories before touching any of them, then migrate, then update only the two pinned
expectations that are meant to change (`WWW-Authenticate` everywhere, `no-store` on
previously-uncovered JSON routes). Bind validation is explicitly out of this module's scope
(D-4).

## D-6. `defaults.py` and the port move

```python
DEFAULT_QUEUE_MAXSIZE = 1000
DEFAULT_BACKOFF_INITIAL_S, DEFAULT_BACKOFF_MAX_S, DEFAULT_BACKOFF_FACTOR = 1.0, 30.0, 2.0
DEFAULT_MAVLINK_ENDPOINT = "udpin:127.0.0.1:14550"
PORT_FTS_TCP = 8087
PORT_MAVLINK2REST = 8088      # external convention — meshsa does not claim it (see below)
PORT_TAK_TLS = 8089
PORT_LLM = 8090
PORT_COMMANDER = 8095
PORT_DETECTION_INGEST = 8097
PORT_HEALTH = 8098            # moved from 8088
PORT_SCOUT_STATION = 8099
PORT_UI = 8100
```

A unit test asserts the table has no duplicate values, and each config model's port default
equals its table entry. **Health moves 8088 → 8098**: 8088 is `mavlink2rest`'s upstream
default, and `ui/cli.py:148-149` provably wires a health listener and a mavlink2rest
consumer into one process — meshsa cannot claim a port an external tool already owns by
convention. Verified during review: 8088 appears in no systemd unit or env-example file; its
only other references are `ops/observability/README.md` (4 lines, including Prometheus scrape
targets) and `cli.py:81`. No compatibility aliasing is added — the CHANGELOG carries an
explicit breaking-default callout ("set `health.port: 8088` / `MESHSA_HEALTH_PORT=8088`
explicitly to keep the old bind"), and the ops README + `docs/AUDIT_M2_AUTH.md` port row are
updated in the same commit.

## D-7. Command-zone hardening posture

Eight gated commits under `packages/meshsa/src/meshsa/command/` and
`flightctl/run_commander.py` — both paths `.claude/governance.yaml`'s scope-freeze denies
editing while `c_gate_met: false`. Every commit: `MESHSA_GOVERNANCE_OVERRIDE` set per the
documented path (logged), `charter-gate-keeper` + `security-reviewer` sign-off, and an
explicit note on whether it's behavior-preserving or hardening.

- **Behavior-preserving (3)**: `Ack.from_message` classmethod (both call sites' *different*
  error policies — link propagates, pump swallows — are kept and documented as deliberate:
  one is a synchronous bounded-retry caller that should fail loud, the other is a
  reader-thread that must survive a malformed frame); typing-only decoupling
  (`command/service.py` depends on a local `LinkHealthReport` Protocol instead of the
  concrete `fpv.link_health.HealthReport`, mirroring `ui/sources.py`'s existing
  `LinkHealthMonitorLike` pattern; the pump's link parameter is typed as the `CommandLink`
  Protocol it already satisfies); `run_commander.build_app`'s three duplicated
  guard→parse→400 blocks collapse into one middleware + `_json_body` helper.
- **Fail-closed hardening (3)** — each gets its own spec-delta scenario (see
  `specs/agent-governance/spec.md`):
  1. *Denied commands are audited.* `stage`/`confirm` currently raise
     (`UnknownCommandError`, `CommandNotAllowedError`, `ForceDisarmDisabledError`,
     `UnknownConfirmationError`, `ForceConfirmationRequired`) **before** the audit record is
     written, so the durable log only ever shows successes and `arm_blocked`. Wrap both in
     `try/except CommandError`, write a `command_denied` record (error type + command name),
     then re-raise.
  2. *Confirmation is unforgeable by construction.* `ConfirmationGate.confirm` returns a
     frozen `ConfirmedCommand(spec, token)` carrying a gate-stamped token field;
     `CommandSender.execute` is narrowed to accept only that type — constructing one directly
     without the gate's stamp is a type error at the call site the gate itself doesn't
     produce, and `build_command` becomes package-private. This closes the gap where
     `execute()`, `send()`, and `build_command` were all public and all accepted a bare
     `CommandSpec`.
  3. *Staged commands expire and are bounded.* `_pending` currently stores
     `dict[str, CommandSpec]` with no timestamp, no TTL, no cap — a `force_disarm` staged on
     the ground stays confirmable in flight, and failed force-confirms accumulate forever.
     Adds `confirmation_ttl_s: float = 60.0` and `pending_cap: int = 8` as `CommanderSettings`
     fields (Invariant 5 — no bare literals), stores `(spec, staged_at)`, rejects/GCs past
     the TTL, enforces the cap, and re-runs the interlock check for every command at confirm
     time (today only `arm` re-checks).
- **Adoption (2)**: `command/config.py` migrates to `_envconfig.py`
  (D-11) and picks up `defaults.PORT_COMMANDER`; `run_commander.py` adopts `_web.py`'s guard
  primitives (the 401-challenge-header delta is explicitly flagged for security review, same
  as D-5).

None of this enables commanding. `c_gate_met` is not read, written, or referenced by any task
in this bundle.

## D-8. Characterization-first testing

Before any migration that changes an observable surface (the four app factories in D-5, the
`_envconfig` collapse, every class split in the tasks list, the scout store rework), a pinning
test lands **first**, in its own commit step, asserting current behavior byte-for-byte
(status codes, headers, response bodies for D-5; the full ~70-key `MESHSA_*` env surface for
`_envconfig`; public method contracts for the class splits). The migration commit then updates
only the pins that correspond to a declared, intentional delta. No fail-closed assertion is
ever satisfied by mocking the guard itself — tests exercise the real `validate_bind`/gate call
with fake I/O at the transport boundary only.

## D-9. What does NOT change: transport registration and bind-guard scan scope

Two corrections made during review, both against the pre-review draft rather than the source
audits:

- **`transports/__init__.py` stays eager.** The file's own first line is *"Built-in
  transports (importing registers them)"* — import-time registration is what populates
  `transport_registry`, and Invariant 1 plus `build_node()`'s skip-unknown-transport-type
  behavior (Invariant 2) both depend on that registry being populated at import. A draft of
  this plan proposed making it lazy to close an `fpv` import cycle; that would have silently
  emptied the registry and is dropped entirely. The cycle in question
  (`meshsa/__init__.py → transports/__init__.py → transports/crsf_source.py → fpv.*`, and
  separately `fpv/tools/* → meshsa.cli → meshsa/__init__.py`) closes through two changes that
  don't touch transport registration at all: the `meshsa/_logging.py` leaf (so `fpv/tools/*`
  stops importing the package root just to call `configure_logging`), and moving
  `HealthReport`/`HealthState` off `fpv.link_health` (which independently removes three of
  the five inbound edges from `command/*`).
- **`bind_guard.py`'s widened scan excludes its own test fixtures.** Naively widening
  `SCAN_GLOBS` to `tools/**/*.py` would flag the linter's own six `LISTENER_TRIGGERS`
  definitions and the eleven trigger-pattern fixtures in
  `tools/claude_hooks/tests/test_bind_guard.py` — the scanner would find itself. The
  corrected glob is `tools/**/*.py` excluding `tools/**/tests/**` and
  `tools/claude_hooks/bind_guard.py` itself, with a pre-scan run in the same commit before any
  fix is applied, so real findings are known upfront rather than discovered mid-commit.

## D-10. TypeScript scope: archive, don't delete

`artifacts/mockup-sandbox` (`src/App.tsx` resolves previews from a `components/mockups/`
directory that does not exist; 5,700+ of its 6,300 lines are unmodified shadcn/ui boilerplate;
no `lint`/`test` script) and `lib/api-client-react` (no `package.json` in the repo depends on
it; only prose references in docs) are moved to `archive/` — the repo's existing convention
for historical snapshots — rather than deleted, so they remain recoverable without relying on
git history archaeology. `api-spec`, `api-zod`, and `api-server` (real consumers verified: the
latter imports the former) are kept and enforced by a new CI `ts` job. The root `Dockerfile`'s
two `COPY ... 2>/dev/null || true` lines referencing `api-client-react` are invalid Dockerfile
syntax today (a bug independent of this program) and are corrected while removing the
now-archived path.

## D-11. `_envconfig.py` — generic env loader

```python
Caster = Callable[[str, str], Any]   # (env_key, raw) -> value

def caster_for(model: type[BaseModel], field_name: str) -> Caster
    # bool -> _parse_bool, int/float -> bounded parsers, tuple[str,...]/frozenset[str] -> csv,
    # everything else -> identity str; raises for nested BaseModel/list fields (sections
    # handle those explicitly).
def env_key(prefix: str, section: str | None, field_name: str) -> str
    # verified mechanical (prefix + optional SECTION_ + FIELD.upper()) against every existing
    # key in config.py's current scalar_maps before the migration commit lands.
def apply_overrides(model, data, env, *, prefix, section=None, casters=None, aliases=None) -> dict
    # aliases carries the small number of absolute (non-mechanical) env keys, e.g.
    # {"mavlink2rest_url": "MESHSA_MAVLINK2REST_URL"} in llm/server.py.
def load_sections(data, env, *, prefix, sections: Mapping[str, type[BaseModel]]) -> dict
def merge_config_json(data, env, *, prefix) -> dict
```

Collapses `NodeConfig.from_env` (162 lines of six copy-pasted section blocks — already
drifted: `RouterConfig` wires 2 of its fields, `HealthConfig` wires all 7), `fpv/config.py`,
`llm/server.resolve_config` (signature preserved; its `parse_int(..., lo=, hi=)` bounds become
caster overrides), and `cli.py`'s ad hoc `_env`/`_env_int`/`_env_float` helpers. Every mechanical
env key is pinned by a frozen characterization test (D-8) before the collapse.
