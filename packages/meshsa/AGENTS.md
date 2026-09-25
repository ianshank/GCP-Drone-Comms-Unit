# MeshSA Framework Agent Guide

This guide applies under `packages/meshsa`. Also follow the root
[../../AGENTS.md](../../AGENTS.md).

## Scope

- Source code lives in [src/meshsa](src/meshsa).
- Tests live in [tests](tests).
- The field CLI is [src/meshsa/examples/base_node.py](src/meshsa/examples/base_node.py)
  and is exposed as the `meshsa-base` console script.

## Traps

- **`AbstractTransport.send` is an `@abc.abstractmethod`.** A transport that subclasses
  neither `PollingSourceTransport` nor `DetectionIngestTransport` and does not define
  `send` **cannot be instantiated at all** — `TypeError` at construction, not a runtime
  `NotImplementedError`. The `raise` in the base body is unreachable and marked
  `# pragma: no cover`. Both receive-only bases no-op `send()` deliberately.
- **Transports register as a side effect of import.** A module that is never imported
  simply has no registry key — the failure looks like a config typo, not a missing
  import.
- **`netauth.validate_bind` guards on `not token`, not `token is None`.** The
  distinction is the fix, not an accident: the commander's former local guard used
  `token is None`, so an empty-string token passed when called directly. Do not
  "tidy" it back.
- **`transports/tak_multicast.py` binds `("", 6969)` — all interfaces — by design**, and
  is a *declared* `bind_guard` exception corresponding to row #2 of
  [../../docs/AUDIT_M2_AUTH.md](../../docs/AUDIT_M2_AUTH.md). It is flagged and
  accepted, not waived-and-forgotten.
- **`meshsa/command/` is frozen** while `.claude/governance.yaml`'s `c_gate_met` is
  false; `scope_freeze` write-denies it. Its ACK policy is fail-closed, its audit
  `fsync` runs off the asyncio loop thread (via `run_in_executor`), and its
  `literal_guard` `"*"` waiver is scoped to `command/config.py` alone — not to the
  directory.
- **`defaults.py` is not the home for *all* literals** — `literal_guard` enforces four
  classes only (`ports`, `hosts`, `magics`, `endpoints`), with six declared waivers
  repo-wide. Its own docstring still describes a staged sweep that is only partly
  done (`code-hygiene-modularity` T-3.5b is unchecked), so treat that line as history.
- **The operator console is read-only but not all-GET.** Invariant I-2 permits exactly
  one mutating-method route, `POST /api/chat`, which answers questions and mutates
  nothing. `tests/test_ui_app.py` asserts the whole route table and ends
  `assert mutating == ["POST"]`. The pump loop is single-threaded — no locks, no
  threads — and an absent source means the route is **not registered** (404), not
  registered-and-empty.
- **`Router` counts `schema_mismatch` separately from `dropped_undecodable`.** Folding
  them loses the only signal that distinguishes a version skew from a corrupt frame.
- **`import meshsa.fpv` must never require the `[fpv]` extra** — `pyserial`/`pyarrow`
  import lazily inside functions. `fpv/version.py::DATASET_SCHEMA` is a *separate*
  version namespace from `meshsa.version::SCHEMA_VERSION`; they are not kept in step.
- **CRSF wire details bite in opposite directions**: CRC8/DVB-S2 (poly `0xD5`) covers
  `[type] + payload` **only**, telemetry payloads are **big-endian**, and RC channels
  are **LSB-first** 11-bit — deliberately the opposite bit order from telemetry.
- **Inference works with no `aiohttp` installed** when an `HttpTransport` is injected;
  `_is_ai_insight` is the guard that stops multi-node feedback loops. Every LLM tool is
  read-only, and both take an empty input schema.
- **Hypothesis's `ci` profile is the default here** (`derandomize=True`,
  `database=None`), so a property test that passes locally is not evidence it passes
  with a different seed.
- **The 97% floor lives in `addopts`**, so it applies to *any* invocation resolving to
  this rootdir — a single-file run included. The one documented escape is
  `fts-e2e.yml`, which passes `--no-cov` explicitly.

## Framework Rules

- Keep transports and codecs registered by import-time factories in
  `meshsa.registry` — why: registration is a side effect of import, so a module that
  is never imported simply has no key; moving registration to call time would make
  "which transports exist" depend on call order.
- New transports should implement the `Transport` Protocol or subclass
  `transports.base.AbstractTransport` when the async inbox pattern fits — why: the
  base supplies the inbox and the `send` contract, and a class that inherits from
  neither silently inherits `AbstractTransport.send`'s raise.
- New codecs must encode/decode `Envelope` and enforce schema compatibility on
  decode — why: the decode boundary is the only place a mixed-version mesh is
  detectable, and nodes are updated one at a time in the field.
- Keep operational defaults in Pydantic config models, not hidden inside router
  or transport logic — why: nodes are reconfigured by environment, never by
  edit-and-redeploy, so a literal buried in logic is unreachable in the field
  — control: `literal_guard` (`tools/claude_hooks/`), whose `SCAN_GLOBS` covers
  `packages/**/src/**/*.py`.
- Tests should use fakes (`LoopbackBus`, injected connectors, `FakeClock`,
  `SeqIdFactory`) instead of live hardware or network dependencies — why: the suite
  must run with no radio, no socket and no TAK server, which is also what makes it
  deterministic — advisory: no checker enforces it; the coverage floor and review do.
- Do not loosen strict mypy to land a feature. Fix the type boundary instead — why: a
  local `ignore` moves the failure to whichever caller trusted the annotation
  — control: `mypy src` runs in CI, and `check_tool_pins.py` keeps the pinned version
  identical across both pyprojects and `.pre-commit-config.yaml`.
- Inference observability: `InferenceService.as_dict()` (`offline_dropped`,
  `offline_queue_depth`, `intake_dropped`, `pending_tasks`) surfaces on `/metrics`
  as `meshsa_inference_*` counters/gauges only when `node.inference_service` is
  set. Task intake is bounded by `NemotronConfig.max_pending_tasks` (env
  `MESHSA_INFERENCE_MAX_PENDING_TASKS`, default `0` = unbounded), drop-and-counted
  into `intake_dropped` past the cap — mirror this pattern if you touch either
  drop path — why: an unbounded queue behind a slow model is an out-of-memory fault
  on a field node, and a drop that is not counted is indistinguishable from no traffic.

## Common Tasks

- Adding a transport: use [../../.agents/skills/meshsa-add-transport/SKILL.md](../../.agents/skills/meshsa-add-transport/SKILL.md).
- Adding a codec: use [../../.agents/skills/meshsa-add-codec/SKILL.md](../../.agents/skills/meshsa-add-codec/SKILL.md).
- Changing the envelope schema: use [../../.agents/skills/meshsa-schema-version-bump/SKILL.md](../../.agents/skills/meshsa-schema-version-bump/SKILL.md).
- Writing tests: use [../../.agents/skills/meshsa-test-conventions/SKILL.md](../../.agents/skills/meshsa-test-conventions/SKILL.md).
- Pre-PR validation and checks: use [../../.agents/skills/pre-pr-validator/SKILL.md](../../.agents/skills/pre-pr-validator/SKILL.md).

## Verification

```powershell
python -m pytest
mypy src
ruff check .
ruff format --check .
python -m build
```
