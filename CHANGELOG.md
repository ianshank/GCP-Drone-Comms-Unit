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

### Added
- `[dev]` extra (pytest, coverage, ruff, mypy, pre-commit, build, twine).
- `LICENSE` (Apache-2.0 placeholder), `CHANGELOG.md`, `CONTRIBUTING.md`,
  `CODE_OF_CONDUCT.md`, `SECURITY.md`.
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
- `MeshConfig` (region/channel/psk/freq_khz) is now threaded to the Meshtastic
  transport and applied to the device at connect via an injectable provisioning
  seam (was dead config). The real device-apply runs only on hardware; the
  wiring is unit-tested with a fake provisioner.
- Transport inbox is now bounded and non-blocking: when full it drops the newest
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
