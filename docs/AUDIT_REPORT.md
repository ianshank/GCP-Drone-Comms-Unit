# Audit Report — jetson-flight-control

<!-- markdownlint-disable MD060 -->

Date: 2026-06-02
Scope: post-reorg + Phase 6 state on branch `feat/agent-harness-and-strict-types`. See
[ARCHITECTURE.md](ARCHITECTURE.md) for the system design and
[CHANGELOG.md](../CHANGELOG.md) for the reorg actions taken.

## Summary

| Dimension | Result |
| --------- | ------ |
| Test count         | **101 passing**                                 |
| Coverage (line)    | **100.00%** (837 stmts, 0 missed)               |
| Coverage (branch)  | **100.00%** (156 branches, 0 missed)            |
| Coverage gate      | `--cov-fail-under=90` (pyproject)               |
| Lint (ruff)        | Clean after auto-fix; 1 rule (`SIM105`) deferred|
| Format (ruff)      | Clean (29 files reformatted during reorg)       |
| Type-check (mypy)  | **Strict clean** (CI required)                  |
| Packaging          | sdist + wheel build green; `meshsa-base` script |
| Docker image       | Not built on this host (no Docker)              |

## 1. Functional / coverage gaps

Statement and branch coverage are at 100% for the framework. The `examples/` package
is excluded from the coverage measurement (it is a runnable example, not
framework code). What's **not** measured by the unit suite:

- **End-to-end integration paths.** A config-driven loopback bridge now validates
  JSON mesh <-> CoT TAK translation through `NodeConfig` and `build_node`. No test
  boots both real `MeshtasticTransport` and `TakTcpTransport` together — they're
  tested in isolation against fakes.
- **Hardware-touching code paths.** The serial-interface builder, the BLE/TCP
  Meshtastic builders, and the live socket-`open_connection` path are
  `# pragma: no cover` (correctly — they require real hardware/network).
- **Failure-mode realism.** Reconnect/backoff is exercised with fake clocks and
  fake interfaces; we do not simulate partial frames, garbled CoT, OS-level
  ENOSPC on the inbox queue, or kernel-level serial drops.

## 2. Missing test categories

| Category | Status | Why it matters |
| -------- | ------ | -------------- |
| Property-based codec roundtrips    | **Absent** | Hypothesis tests would catch CoT/Compact edge cases |
| End-to-end Meshtastic <-> TAK      | **Partial** | Config-driven loopback bridge covered; real transports remain fake-isolated |
| Multicast group join/leave         | **Absent** | UDP transport tested at the framing level only  |
| Dedupe LRU eviction at scale       | **Absent** | Cache size in config, behavior at full capacity unverified |
| Async backpressure / inbox full    | **Absent** | What happens when a slow subscriber holds the queue? |
| Schema-mismatch drop counters      | **Absent** | We log on drop but do not expose a metric       |
| Long-soak / fuzz on real hardware  | **Absent** | Out of scope for unit CI; nightly / lab task    |

## 3. Backward-compatibility scan

Wire compatibility is implemented but minimal:

- `meshsa.version` exposes `SCHEMA_VERSION = 1` and `MIN_COMPATIBLE_SCHEMA = 1`.
- `JsonCodec`, `CompactCodec`, and `CotCodec` all gate on `is_compatible(v)` and
  raise `IncompatibleSchemaError` (router catches and drops).
- `build_node()` skips unknown transport types — older builds tolerate newer
  configs.

Recommendations for a 1.0 hardening pass:

| Action | Why |
| ------ | --- |
| Add `warnings.warn(..., DeprecationWarning)` markers when fields are renamed/aliased | Today renaming a model field is a hard break |
| Per-codec `supported_schemas: frozenset[int]`   | Enables Codec v1 and v2 to coexist on the same node       |
| Document the bump policy in `CHANGELOG.md`      | `CONTRIBUTING.md` already references it; CHANGELOG should formalize |
| Counter / metric for dropped frames             | Currently a log line; observability needs a number        |
| Snapshot test for serialized envelopes          | Catch accidental wire-format breakage in PR review        |

## 4. Modularity scan

Strengths confirmed:

- Pluggable transports + codecs via `Registry[T]` with import-time registration.
- DI surface is `typing.Protocol` (`Transport`, `Codec`, `Clock`, `IdFactory`).
- Per-transport codec selection cleanly bridges JSON mesh <-> CoT / TAK.
- No god modules; every file is short and single-purpose.

Coupling / extensibility gaps to address in a follow-up:

| Finding | Impact |
| ------- | ------ |
| `node.build_node()` instantiates registry codecs by string name only | Can't inject a custom-configured codec instance at runtime; must register-then-build |
| `router.py` imports `models.Envelope` directly | Tight coupling to the Pydantic class; a structural `EnvelopeLike` Protocol would loosen it |
| No entry-point plugin discovery                | Out-of-tree transports must be imported eagerly. A `meshsa.transports` entry-point group would let third-party packages publish drivers via `pip install` |
| Examples folder is part of the wheel           | Acceptable (gives us a console script) but drags `argparse` into the package import graph; could move CLI out of examples/ |

## 5. Dependency hygiene

| Dep | Before | After | Notes |
| --- | ------ | ----- | ----- |
| pydantic    | `>=2` (unbounded)    | `>=2,<3`                | Major bump = breaking; cap  |
| structlog   | `>=23` (unbounded)   | `>=23,<26`              | Cap at next major           |
| pytest      | implicit             | `[dev]` extra           | Now declared                |
| pytest-cov  | implicit             | `[dev]` extra           | Now declared                |
| pytest-asyncio | implicit          | `[dev]` extra           | Now declared                |
| meshtastic  | implicit (install README) | `[meshtastic]` extra | Was undocumented in pyproject |
| pypubsub    | implicit             | `[meshtastic]` extra    | Same                        |
| ruff        | none                 | `[dev]` extra           | New                         |
| mypy        | none                 | `[dev]` extra           | New                         |
| pre-commit  | none                 | `[dev]` extra           | New                         |
| build/twine | none                 | `[dev]` extra           | New                         |

## 6. Operational gaps

| Gap | Recommendation |
| --- | -------------- |
| No health-check endpoint                     | Expose `/healthz` over a tiny aiohttp listener (opt-in)     |
| No Prometheus metrics                        | Counters: rx/tx per transport, dropped, schema-mismatch, reconnects |
| Structured logs ship to stderr only          | Document forwarding to journald / vector / fluent-bit       |
| `KillSignal=SIGINT` was missing from systemd | Fixed in this reorg; verify on a real Pi                    |
| No Docker image previously                   | `tools/Dockerfile` added (multi-stage, non-root user, tini) |
| No CI                                        | `.github/workflows/ci.yml` added (matrix py3.10/3.11/3.12)  |
| LICENSE was missing                          | `LICENSE` added (Apache-2.0 placeholder; **owner must confirm**) |

## 7. Lint / type baseline

Ruff: clean. The `SIM105` rule (`try/except/pass` -> `contextlib.suppress`) is
deferred via pyproject ignore — 7 sites, all behaviorally equivalent rewrites
in `router.py`, `meshtastic_radio.py`, `tak.py`, and `examples/base_node.py`.

Mypy `--strict` is now clean when run package-locally via `cd packages/meshsa &&
mypy src`. CI runs this as a required check. The prior baseline errors were fixed
by tightening the `Codec` Protocol, parameterizing registries and task fields,
typing compact payload branches, narrowing CoT XML elements, and making the
base-node environment helper non-optional for argparse defaults.

## 8. Prioritized backlog

All items below were addressed in the enterprise-remediation branch
`feat/enterprise-remediation` (see `CHANGELOG.md`); PR references are the
conventional-commit units.

### P0 (do before 0.2.0)

1. ✅ Confirm the `LICENSE` — confirmed **Apache-2.0**, placeholder wording removed (PR2).

### P1 (next iteration)

1. ✅ `SIM105` cleanups (`contextlib.suppress`) + rule re-enabled (PR2).
2. ✅ Per-codec `supported_schemas: frozenset[int]` (JSON/Compact gate; CoT
   schema-agnostic) (PR3).
3. ✅ Hypothesis property tests for codec round-trips (PR6).
4. ✅ `RouterMetrics` (rx/tx/forwarded/dropped/schema-mismatch) + per-transport
   reconnect counters + opt-in `/healthz` (PR4).
5. ✅ CLI moved to `meshsa.cli`; `examples/` is now a thin re-export (PR5).

### P2 (nice to have)

1. ✅ Entry-point plugin groups `meshsa.transports` / `meshsa.codecs` (PR7).
2. ✅ Serialized-envelope snapshot tests (`tests/snapshots/`) (PR6).
3. ✅ Opt-in Docker image publish to GHCR on tag (PR9).
4. ✅ Nightly workflow (full-extras gate + `@pytest.mark.slow` hook); on-hardware
   soak remains a lab task (no hardware in CI) (PR9).

## 9. Dead-config / packaging gaps found during remediation (beyond the original audit)

1. ✅ `RouterConfig.queue_maxsize` was inert — now wired to transport inboxes (PR1).
2. ✅ `MeshConfig` (region/channel/psk/freq_khz) never reached the radio — now
   threaded to the Meshtastic transport and applied at connect/reconnect via an
   injectable provisioner seam (PR1).
3. ✅ Missing PEP 561 `py.typed` despite strict typing — added + shipped in the wheel (PR2).
4. ✅ Transport inbox could block under backpressure — now bounded drop-newest
   with a `dropped_inbox_full` counter on all inbound paths (PR1).
5. ✅ `_default_pubsub` typing failed strict mypy with `[meshtastic]` installed —
   fixed; a nightly job now type-checks against the full dependency graph (PR1, PR9).

## 10. Verification record

Original audit (2026-06-02):

```text
$ pytest                                                # 101 passed; 100% line, 100% branch
```

Post-remediation (2026-06-03, branch `feat/enterprise-remediation`):

```text
$ cd packages/meshsa && pytest      # 137 passed; 100% line (983 stmts), 100% branch (176)
$ mypy src                          # Success: no issues found in 23 source files (with [meshtastic] installed)
$ ruff check . && ruff format --check .   # All checks passed!
$ python -m build                   # sdist + wheel; py.typed present in the wheel
$ meshsa-base --help                # console script works (-> meshsa.cli:main)
```
