# meshsa-core — shared primitives distribution

> **Status: Definition.** (Definition → Implemented → Validated; see
> [README.md](README.md).) Pairs with [../CHARTER.md](../CHARTER.md) (scope + invariants),
> [../ROADMAP.md](../ROADMAP.md) (milestone), and
> [../IMPLEMENTATION_PLAN.md](../IMPLEMENTATION_PLAN.md) (track). Change deliberately; code
> docstrings cite this spec's `§` numbers.

**Milestone / Initiative:** M2-adjacent hygiene enabler (`code-hygiene-modularity` OpenSpec
bundle) **Track:** hygiene/modularity **Author:** implementing agent, 2026-07-30

---

## 1. Scope

Deliverables in priority order:

1. A new distribution, `meshsa-core` (import package `meshsa_core`), under
   `packages/meshsa_core/`, holding the primitives `meshsa` and `jetson_yolo_gcs` both need:
   an injectable `Clock` protocol, a name-to-factory `Registry`, structured logging setup,
   heartbeat-freshness gating, the bind-guard authentication primitives, and MAVLink
   connection-resolution glue.
2. `meshsa` adoption via explicit re-export shims — every existing public import path
   (`meshsa.protocols.Clock`, `meshsa.netauth.validate_bind`, `meshsa.registry.Registry`,
   `meshsa.transports.backoff.Backoff`) keeps resolving.
3. `jetson_yolo_gcs` adoption via the same shim pattern, replacing five modules the package
   currently forks byte-for-byte from `meshsa` (documented in each forked module today as an
   intentional "self-contained" copy).

### Non-goals (explicitly deferred)

- Extracting anything beyond the primitives named above — codecs, transports, and
  domain models stay in `meshsa`.
- Changing either consumer's public exception hierarchy (`MeshSAError` vs. `JetsonYoloError`
  subclassing is preserved via injectable registry error types, §5).
- Publishing `meshsa-core` to a package index — it is consumed as an in-repo editable install
  via `pip install -e packages/meshsa_core`, matching how `meshsa` and `jetson_yolo_gcs` are
  installed today (`AGENTS.md` command table).
- Lifting `jetson_yolo_gcs`'s CHARTER §3 "no runtime dependency on `meshsa`" constraint
  beyond the narrow amendment this spec requires — that constraint's rationale (the package
  stays usable as a standalone library) is preserved because `meshsa_core` itself has no
  dependency on the `meshsa` framework.

---

## 2. Facts the implementation relies on

- `meshsa.registry.Registry` raises exceptions from `meshsa.errors` (a `MeshSAError`/
  `KeyError`/`ValueError` multiple-inheritance hierarchy with existing test coverage);
  `jetson_yolo_gcs.core.registry.Registry` raises `JetsonYoloError` subclasses. Both are
  public, tested catch surfaces that must not change identity.
- `mypy --strict` is configured with `warn_unused_ignores` and (repo-wide convention)
  `no_implicit_reexport` semantics — re-exports require the explicit `as` form
  (`from x import Y as Y`).
- `tools/claude_hooks/bind_guard.py`'s single-primitive rule (verified at
  `bind_guard.py:186-205`) fires on any `def validate_bind` outside the module named in
  `.claude/governance.yaml`'s `bind_guard.canonical_module`, unless that definition's body
  demonstrably delegates to the canonical symbol. The four existing per-service adapters
  already satisfy this shape and must continue to after the canonical module changes.
- `packages/meshsa/src/meshsa/transports/__init__.py` registers every built-in transport at
  import time; this is load-bearing for `transport_registry` (CHARTER §4 Invariant 1) and is
  not touched by this extraction.

---

## 3. Architecture

```
packages/meshsa_core/src/meshsa_core/
  errors.py      CoreError, DuplicateRegistrationError, UnknownComponentError (injectable defaults)
  registry.py    Registry[T] with injectable duplicate_error/unknown_error types
  clock.py       Clock (Protocol, runtime_checkable), SystemClock, MonotonicClock
  logging.py     configure_logging(level, *, json_logs=False), log_level_num
  heartbeat.py   HeartbeatReport, HeartbeatMonitor
  backoff.py     Backoff, SleepFn, BackoffSettings
  netauth.py     is_loopback, authorize, validate_bind, TransportAuthPolicy, NetAuthPolicy
  mavlink.py     resolve_connection, extract_endpoint_host
  version.py     __version__
```

`meshsa/protocols.py`, `meshsa/netauth.py`, `meshsa/transports/backoff.py`, `meshsa/cli.py`
(logging), and `meshsa/registry.py` become re-export shims (the last a thin subclass, not a
pure re-export — see §5). `jetson_yolo_gcs/core/clock.py`, `core/registry.py`,
`core/logging.py`, and `mavlink/heartbeat.py` become the equivalent shims;
`mavlink/bridge.py`'s `_default_connection_factory` delegates to
`meshsa_core.mavlink.resolve_connection`.

No component in this package performs I/O beyond what its moved counterpart already did
(`mavlink.py`'s `resolve_connection` lazily imports `pymavlink`, matching both consumers'
existing `# pragma: no cover` glue pattern). Tests reach every component with fakes; the
`mavlink` extra's `pymavlink`-touching glue is the only pragma'd path, consistent with
Invariant 6.

---

## 4. Behaviour / state model

No new state machine. `Registry` and `Clock` are unchanged in behavior — only their error
types become a constructor parameter (defaulted, so no call site changes). `netauth`'s
fail-closed `validate_bind` behavior is moved verbatim, byte-for-byte, with a characterization
test asserting the moved module's decode/validate outcomes match the pre-move module's before
the shim replaces it. `HeartbeatMonitor`/`HeartbeatReport` freshness semantics are unchanged;
the freshness *predicate* used elsewhere in the tree is unified separately (see the
`code-hygiene-modularity` bundle's task T-5.3), not as part of this extraction.

---

## 5. Module specifications

### `registry.py`

```python
class Registry(Generic[T]):
    def __init__(
        self, kind: str, *,
        duplicate_error: type[Exception] = DuplicateRegistrationError,
        unknown_error: type[Exception] = UnknownComponentError,
    ) -> None: ...
```

`meshsa.registry.Registry` subclasses this, pinning `duplicate_error`/`unknown_error` to
`meshsa`'s existing error types so `isinstance`/`except MeshSAError` sites are unaffected.
`jetson_yolo_gcs.core.registry.Registry` mirrors it with jetson's error types.

### Config fields (CHARTER §4.5 — no magic numbers)

`meshsa_core` itself is a primitives library, not a service — it has no operational
configuration of its own. The one constant it introduces, `BackoffSettings`
(`initial_s`/`max_s`/`factor`), is a frozen dataclass whose defaults are supplied by callers
(the `code-hygiene-modularity` bundle's `defaults.py` sources them); it does not read
environment variables itself.

---

## 6. Wire / schema posture (backward compatibility)

**N/A** — no wire change. This is a code-organization extraction; no `Envelope`, transport
frame, or config-file schema changes shape.

---

## 7. Test plan (by category)

- **Unit** — every moved module's existing test file relocates with it (registry, clock,
  backoff, netauth, heartbeat); `Registry`'s injectable error types get a dedicated test
  (default types vs. injected types raise the expected class).
- **Anti-cycle** — a test imports every `meshsa_core` submodule and asserts `"meshsa"` and
  `"jetson_yolo_gcs"` are absent from `sys.modules` afterward.
- **Shim equivalence** — for each re-export, a test asserts `meshsa.protocols.Clock is
  meshsa_core.clock.Clock` (identity, not just interface compatibility) so `isinstance`
  checks against either path behave identically.
- **Security** — `netauth`'s existing fail-closed test suite (including the empty-token edge
  case) moves with the module; the `bind_guard` CI check itself is the integration test that
  the canonical-module change doesn't break any of the four per-service adapters.
- **Regression** — full `meshsa` and `jetson_yolo_gcs` suites stay green throughout the
  adoption commits (T-7.2, T-7.3), gates unchanged (97% / 96%).

Coverage floor: `meshsa_core` carries its own `--cov-fail-under=97`, matching `meshsa`'s.

---

## 8. Exit criteria

- **Mechanism (binary):** §7 green; `ruff`/`ruff format`/`mypy --strict`/`pytest` green for
  all three packages; `meshsa_core`'s coverage floor met; `bind_guard.py` clean against the
  new canonical module; CHANGELOG + NEXTSTEPS updated; spec status → `Implemented`.
- **Validation (separate):** none required beyond the mechanism gate — this is a pure
  code-organization change with no hardware/bench surface. Status moves directly to
  `Implemented` once the mechanism gate is met (no `Validated` phase applies).

---

## 9. CHARTER §4 invariant checklist

| # | Invariant | How this design preserves it |
|---|-----------|------------------------------|
| 1 | Open/closed registry extensibility | `Registry` API unchanged; `transport_registry`/`codec_registry` singletons stay in `meshsa`, untouched — only the generic `Registry` class relocates |
| 2 | Versioned, backward-compatible wire | N/A — no wire surface in this extraction |
| 3 | DI via `Protocol`, tests need no hardware | `Clock` stays a `runtime_checkable` Protocol; `mavlink.py`'s glue is the only pragma'd path |
| 4 | Stateful I/O in transports/services, not codecs | Unaffected — no codec touched |
| 5 | Config-driven, no magic numbers | `BackoffSettings` is caller-supplied defaults, not a hardcoded constant inside `meshsa_core` |
| 6 | Quality gates green; hardware glue is the only `# pragma: no cover` | `meshsa_core`'s own gate at 97%; `mavlink.py`'s lazy `pymavlink` import is the sole pragma |
| 7 | No secrets / machine fingerprints in repo | Unaffected — no config/secrets surface in this package |
