# Audit Report — jetson-flight-control

Date: 2026-06-02
Scope: post-reorg state on branch `chore/enterprise-reorg`. See
[ARCHITECTURE.md](ARCHITECTURE.md) for the system design and
[CHANGELOG.md](../CHANGELOG.md) for the reorg actions taken.

## Summary

| Dimension          | Result                                          |
|--------------------|-------------------------------------------------|
| Test count         | **98 passing** (baseline + post-reorg)          |
| Coverage (line)    | **100.00%** (827 stmts, 0 missed)               |
| Coverage (branch)  | **100.00%** (156 branches, 0 missed)            |
| Coverage gate      | `--cov-fail-under=90` (pyproject)               |
| Lint (ruff)        | Clean after auto-fix; 1 rule (`SIM105`) deferred|
| Format (ruff)      | Clean (29 files reformatted during reorg)       |
| Type-check (mypy)  | **28 strict-mode errors** (baseline; non-gating)|
| Packaging          | sdist + wheel build green; `meshsa-base` script |
| Docker image       | Not built on this host (no Docker)              |

## 1. Functional / coverage gaps

Statement and branch coverage are at 100% for the framework. The `examples/` package
is excluded from the coverage measurement (it is a runnable example, not
framework code). What's **not** measured by the unit suite:

- **End-to-end integration paths.** No test boots both `MeshtasticTransport` and
  `TakTcpTransport` together — they're tested in isolation against fakes.
- **Hardware-touching code paths.** The serial-interface builder, the BLE/TCP
  Meshtastic builders, and the live socket-`open_connection` path are
  `# pragma: no cover` (correctly — they require real hardware/network).
- **Failure-mode realism.** Reconnect/backoff is exercised with fake clocks and
  fake interfaces; we do not simulate partial frames, garbled CoT, OS-level
  ENOSPC on the inbox queue, or kernel-level serial drops.

## 2. Missing test categories

| Category                           | Status     | Why it matters                                  |
|------------------------------------|------------|-------------------------------------------------|
| Property-based codec roundtrips    | **Absent** | Hypothesis tests would catch CoT/Compact edge cases |
| End-to-end Meshtastic <-> TAK      | **Absent** | The bridge is the product; only unit-level today|
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

| Action                                          | Why                                                       |
|-------------------------------------------------|-----------------------------------------------------------|
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

| Finding                                        | Impact                                                              |
|------------------------------------------------|---------------------------------------------------------------------|
| `node.build_node()` instantiates registry codecs by string name only | Can't inject a custom-configured codec instance at runtime; must register-then-build |
| `router.py` imports `models.Envelope` directly | Tight coupling to the Pydantic class; a structural `EnvelopeLike` Protocol would loosen it |
| No entry-point plugin discovery                | Out-of-tree transports must be imported eagerly. A `meshsa.transports` entry-point group would let third-party packages publish drivers via `pip install` |
| Examples folder is part of the wheel           | Acceptable (gives us a console script) but drags `argparse` into the package import graph; could move CLI out of examples/ |

## 5. Dependency hygiene

| Dep         | Before               | After                   | Notes                       |
|-------------|----------------------|-------------------------|-----------------------------|
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

| Gap                                          | Recommendation                                              |
|----------------------------------------------|-------------------------------------------------------------|
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

Mypy `--strict` (run via `mypy packages/meshsa/src`):

| File                                | Errors |
|-------------------------------------|--------|
| `transports/meshtastic_radio.py`    | (resolved by `[mypy.overrides]` for missing stubs) |
| `cot.py`                            | 2 (kwargs splat into typed init)                  |
| `compact.py`                        | 2 (dict typing)                                   |
| `router.py`                         | 2 (`object` -> `Envelope` narrowing)              |
| `node.py`                           | 3 (`Codec | None` propagation)                    |
| `examples/base_node.py`             | ~6 (env-var `int(...)` / `float(...)` on `str | None`) |

CI pipeline runs mypy with `continue-on-error: true` so the type baseline does not
block PRs today; flip to required once the 28 errors above are addressed.

## 8. Prioritized backlog

### P0 (do before 0.2.0)
1. Confirm or replace the `LICENSE` placeholder with the chosen license.
2. Fix the 28 mypy strict errors and remove `continue-on-error` from CI.
3. Add an end-to-end integration test for the Meshtastic <-> TAK bridge using
   `LoopbackTransport` on both sides.

### P1 (next iteration)
4. Add the `SIM105` cleanups (`contextlib.suppress`) and re-enable the rule.
5. Add `supported_schemas: frozenset[int]` to each codec; let codecs coexist.
6. Add Hypothesis-based property tests for codec roundtrips.
7. Expose dropped-frame and reconnect counters; add a `/healthz` endpoint.
8. Move the runnable CLI out of `examples/` into a `meshsa.cli` module so the
   examples folder stays demonstrative-only.

### P2 (nice to have)
9. Entry-point plugin group `meshsa.transports` for out-of-tree drivers.
10. Snapshot tests for serialized envelopes (`tests/snapshots/`).
11. Build and publish the Docker image from CI on tag.
12. Add a soak / fuzz job (nightly) on actual hardware in the lab.

## 9. Verification record

```
$ pytest                                                # 98 passed in 0.88s; 100% line, 100% branch
$ ruff check packages/meshsa                            # All checks passed!
$ ruff format --check packages/meshsa                   # 31 files already formatted
$ mypy packages/meshsa/src                              # 28 errors recorded as baseline
$ python -m build                                       # meshsa-0.1.0.tar.gz, meshsa-0.1.0-py3-none-any.whl
$ meshsa-base --help                                    # console script works
$ grep -r "meshsa_framework|pi5_node_kit|meshsa_base_service|jetson_gcs_stls|usernode_stls"
                                                        # zero hits
```
