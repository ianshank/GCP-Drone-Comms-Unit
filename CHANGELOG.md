# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- Repository reorganized into enterprise layout: `packages/`, `ops/`, `hardware/`,
  `docs/`, `tools/`, `.github/`, `archive/`.
- 22 duplicated root files removed (canonical copies live in their domain
  subfolders); ZIP snapshots moved to `archive/`.
- `meshsa` package now lives at `packages/meshsa/` (was `meshsa_framework/meshsa/`).
- `examples/base_node.py` moved into the importable package at
  `src/meshsa/examples/base_node.py` and exposed as the `meshsa-base` console script.
- `meshsa-base.service` updated to call `meshsa-base` and use `KillSignal=SIGINT`.
- Runtime dependencies pinned with upper bounds (`pydantic>=2,<3`, `structlog>=23,<26`).
- `meshtastic` and `pypubsub` moved to the `[meshtastic]` optional extra.
- CI now runs strict mypy as a required package-local check.
- Type hints tightened across codecs, registry, router, node assembly, transports,
  and the base-node example without changing runtime behavior.
- Re-enabled the `SIM105` ruff rule and rewrote the 7 `try/except: pass` sites as
  `contextlib.suppress(...)`; the rule is no longer ignored.
- Confirmed the project license as Apache-2.0 (dropped the "placeholder" wording).
- Moved the runnable CLI from `examples/base_node.py` into the importable
  `meshsa.cli` module (the example is now a thin re-export so `examples/` stays
  demonstrative-only); the `meshsa-base` console script targets `meshsa.cli:main`
  (name unchanged, so the systemd unit is unaffected). Added
  `--health/--healthz-host/--healthz-port` flags.

### Added
- `[dev]` extra (pytest, coverage, ruff, mypy, pre-commit, build, twine).
- `LICENSE` (Apache-2.0), `CHANGELOG.md`, `CONTRIBUTING.md`,
  `CODE_OF_CONDUCT.md`, `SECURITY.md`.
- `py.typed` marker (PEP 561) so downstream consumers get `meshsa`'s types;
  packaged via `[tool.setuptools.package-data]`.
- Per-codec `supported_schemas` (`frozenset[int]`): codecs accept the full
  compatibility window by default (`version.SUPPORTED_SCHEMAS`) but can be built
  with an explicit set so multiple codec/schema versions can coexist on one node.
  `JsonCodec`/`CompactCodec` gate decode on membership; `CotCodec` is
  schema-agnostic (CoT XML carries no meshsa schema). Additive and
  behavior-preserving — no `SCHEMA_VERSION` bump.
- Observability: `Router.metrics` (`RouterMetrics`: rx, tx, forwarded,
  dropped_undecodable, schema_mismatch — the last two split via a dedicated
  `IncompatibleSchemaError` branch in the pump) and per-transport `reconnects`
  counters on the Meshtastic and TAK-TCP supervisors.
- `meshsa.health.health_snapshot(node)` (pure, JSON-able status + metrics) and an
  opt-in `/healthz` aiohttp listener (`serve_healthz`) behind a new `[health]`
  extra; `aiohttp` is imported lazily so the module loads without it.
- `HealthConfig` (`NodeConfig.health`: enabled/host/port).
- Hypothesis property tests for codec round-trips (JSON lossless; Compact PLI
  within scale tolerance; Compact CHAT text preserved) — `hypothesis` added to `[dev]`.
- Serialized-envelope snapshot tests (`tests/snapshots/`) for JSON/Compact/CoT of a
  pinned canonical envelope, to catch accidental wire-format breakage
  (regenerate with `MESHSA_UPDATE_SNAPSHOTS=1`).
- Transport-level multicast group join/leave test for `TakMulticastTransport`.
- Opt-in out-of-tree plugin discovery: `meshsa.plugins.load_plugins()` loads the
  `meshsa.transports` / `meshsa.codecs` entry-point groups (py3.10–3.12 metadata
  compat shim), skipping any broken driver. Not called implicitly.
- `build_node(codec_instances=...)` injects a pre-configured `Codec` instance per
  transport (preferred over registry-by-name), closing the audit's modularity gap
  where a codec could only be referenced by name.
- `meshsa.version.warn_deprecated(old, replacement, removed_in=...)` helper to emit
  `DeprecationWarning` on renamed fields/options, per the compatibility policy.
- `.github/workflows/nightly.yml`: scheduled run that installs the full extras
  (`[dev,meshtastic,health]`) and runs mypy + the suite against the real optional
  dependency graph (catching optional-dep typing drift the `[dev]`-only CI can't),
  plus any `@pytest.mark.slow` soak tests. Registered the `slow` pytest marker.
- `release.yml`: opt-in GHCR image publish on `v*` tags (gated on the
  `PUBLISH_DOCKER` repo variable, using the built-in `GITHUB_TOKEN`).
- Docker runtime image now installs the `[meshtastic,health]` extras.
- `docs/ARCHITECTURE.md`, `docs/AUDIT_REPORT.md`.
- `.github/workflows/ci.yml` (matrix py3.10/3.11/3.12), `.github/workflows/release.yml`.
- `.pre-commit-config.yaml`, `tools/Dockerfile`, `tools/Makefile`.
- Config-driven bridge e2e coverage for JSON mesh <-> CoT TAK translation through
  `NodeConfig` and `build_node`.
- Enterprise agent harness: `AGENTS.md`, `CLAUDE.md`, Copilot instructions,
  scoped folder guidance, custom agent modes, and project skills.

### Fixed
- `RouterConfig.queue_maxsize` is now applied to transport inbox queues (was
  dead config); a per-transport `options.queue_maxsize` still overrides it.
- `MeshConfig` is now threaded to the Meshtastic transport (was dead config) and
  applied to the device via an injectable provisioning seam, on the initial
  connect **and re-applied after every reconnect**. Scope: the default
  provisioner applies `region` (passthrough) and persists it; `channel`/`psk`/
  `freq_khz` are logged as pending firmware-specific implementation rather than
  silently claimed. The control flow is fully unit-tested with a fake device.
- Transport inbox is now bounded and non-blocking across **all** inbound paths
  (including the Meshtastic receive callback): when full it drops the newest
  frame and counts it (`dropped_inbox_full`) instead of stalling the reader —
  relevant now that `queue_maxsize` is configurable.
- `_default_pubsub()` return typing corrected (cast) so strict mypy passes with
  the `[meshtastic]` extra installed, not only in the `[dev]`-only CI env.
- De-duplicated the `9999999.0` CoT/error sentinel into a shared
  `meshsa.models.UNKNOWN_ERROR_M` used by both the model and the CoT codec.

## [0.1.0] - 2026-06-02

### Added
- Initial framework release: schema-versioned `Envelope`, registry-based codec and
  transport plug-in points, async `Router` with per-transport codec selection and
  message dedupe, JSON / CoT / compact codecs, Loopback / Meshtastic / TAK transports.
- 98-test suite, 100% line + branch coverage.
