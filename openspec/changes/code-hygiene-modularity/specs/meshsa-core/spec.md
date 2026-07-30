# Spec Delta: meshsa-core (new capability)

## ADDED Requirements

### Requirement: Shared Primitives Live in One Distribution
The primitives that `meshsa` and `jetson_yolo_gcs` both need — an injectable `Clock`
protocol, a name-to-factory `Registry`, structured logging setup, heartbeat-freshness
gating, the bind-guard authentication primitives (`is_loopback`/`authorize`/
`validate_bind`), and MAVLink connection-resolution glue — SHALL be published from exactly
one package, `meshsa-core` (import name `meshsa_core`), rather than forked per consumer.

#### Scenario: A primitive is needed by both consumers
- **WHEN** `meshsa` or `jetson_yolo_gcs` needs `Clock`, `Registry`, `configure_logging`,
  heartbeat gating, or bind-guard auth
- **THEN** it imports from `meshsa_core`, directly or through its own package's re-export
  shim — never from a parallel implementation

### Requirement: No Framework Dependency
`meshsa_core` SHALL depend on nothing beyond the standard library and `structlog` (plus an
optional `mavlink` extra for MAVLink-specific glue), and SHALL NOT import `meshsa` or
`jetson_yolo_gcs`.

#### Scenario: Anti-cycle check
- **WHEN** every module under `meshsa_core` is imported in a fresh interpreter
- **THEN** neither `meshsa` nor `jetson_yolo_gcs` appears in `sys.modules` afterward

### Requirement: Registry Error Types Are Injectable Per Consumer
`meshsa_core.registry.Registry` SHALL accept `duplicate_error`/`unknown_error` type
parameters (defaulting to `meshsa_core`'s own error types) so each consumer can subclass to
preserve its existing public exception hierarchy without `meshsa_core` needing to know about
either consumer's error taxonomy.

#### Scenario: meshsa's registry raises meshsa's error types
- **WHEN** `meshsa.registry.Registry` (a thin subclass pinning meshsa's error types) raises on
  a duplicate registration or an unknown lookup
- **THEN** the raised exception is an instance of `meshsa.errors.MeshSAError`, exactly as
  before the extraction — no `except MeshSAError` call site anywhere in `meshsa` changes

### Requirement: Public Import Paths Survive the Extraction
Every symbol that moves into `meshsa_core` SHALL remain importable from its pre-extraction
location in `meshsa` (and, where applicable, `jetson_yolo_gcs`) via an explicit re-export.

#### Scenario: Existing import keeps working
- **WHEN** code imports `Clock` from `meshsa.protocols`, `validate_bind` from
  `meshsa.netauth`, or `Backoff` from `meshsa.transports.backoff`
- **THEN** the import resolves to the same object as importing from `meshsa_core` directly,
  and `mypy --strict` (with `no_implicit_reexport`) accepts the re-export without error
