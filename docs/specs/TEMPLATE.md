# <Title> — <one-line scope>

> **Status: Definition.** (Definition → Implemented → Validated; see
> [README.md](README.md).) Pairs with [../CHARTER.md](../CHARTER.md) (scope + invariants),
> [../ROADMAP.md](../ROADMAP.md) (milestone), and [../IMPLEMENTATION_PLAN.md](../IMPLEMENTATION_PLAN.md)
> (track). Change deliberately; code docstrings cite this spec's `§` numbers.

**Milestone / Initiative:** <M_/Initiative _>  **Track:** <plan track>  **Author:** <name/date>

---

## 1. Scope

Deliverables in priority order. State precisely what ships.

### Non-goals (explicitly deferred)

What this spec does **not** cover (prevents scope creep; cite the CHARTER non-goal it respects).

---

## 2. Facts the implementation relies on

Protocol/interface/hardware facts the design depends on (endianness, message layouts, API
shapes, cadence, units). Each fact that varies in the field becomes a config field in §5, not a
literal in code. Cite upstream sources (specs, vendor docs) so assumptions are auditable.

---

## 3. Architecture

A small diagram and the data flow. Name the seams: which `Protocol`s are injected, which
registry the new transport/codec/backend registers through, where stateful I/O lives (in the
transport/service, never the codec). Tests must reach every component with fakes — no hardware.

---

## 4. Behaviour / state model

The normative rules: state machine, failure policy (per-path, not a blanket catch), retry/ack
semantics, safety authority (what it may and may not do). For any **safety write path**, state
the fail-closed behaviour explicitly and what "healthy" must never silently mean.

---

## 5. Module specifications

Per module: public types/functions, the `Protocol` it satisfies, and its **config fields**.

> **No magic numbers (CHARTER §4.5).** Every operational value is a config field with an
> explicit default and (where operator-facing) an env-var binding. List them here as a table:

| Field | Type | Default | Env binding | Meaning |
| ----- | ---- | ------- | ----------- | ------- |
| `<name>` | `<type>` | `<default>` | `<PREFIX_NAME>` | <what it controls> |

---

## 6. Wire / schema posture (backward compatibility)

State one explicitly:

- **Additive, no bump** — new optional payload keys emitted via `exclude_none`; old readers see
  byte-identical output. (Preferred; cite the M3.1 additive pattern.)
- **Envelope-shape change → full bump ritual** — update `meshsa.version`
  (`SCHEMA_VERSION`/`MIN_COMPATIBLE_SCHEMA`), tests, docs, and `CHANGELOG.md`. Use the
  `meshsa-schema-version-bump` skill. Peers accept `[MIN_COMPATIBLE_SCHEMA, SCHEMA_VERSION]`.
- **N/A** — no wire change.

---

## 7. Test plan (by category)

Fakes-first, no hardware in unit tests. State the **coverage floor** for the new modules
(meshsa ≥90% total, safety files at 100%; `jetson_yolo_gcs` ≥85%). Cover, as applicable:

- **Unit** — each module in isolation with fakes / `FakeClock` / `SeqIdFactory`.
- **Integration** — components wired through the router/service/pipeline.
- **Functional / edge** — boundaries: queue-full, cache eviction, stale/age, malformed input.
- **Security** — missing/secret config, no secret leak in logs, fail-closed on bad bind/auth.
- **Property-based** — Hypothesis roundtrips for codecs where applicable.
- **Golden vectors** — for parsers/encoders, with a wrong-decode negative assertion.

---

## 8. Exit criteria

- **Mechanism (binary):** §7 green; gates (`ruff`/`ruff format`/`mypy --strict`/`pytest`) green;
  coverage floor met; CHANGELOG + NEXTSTEPS updated; spec status → `Implemented`.
- **Validation (separate):** the hardware/bench checks that move status → `Validated`
  (thresholds stay provisional until measured — mirror the FPV §8 split).

---

## 9. CHARTER §4 invariant checklist

| # | Invariant | How this design preserves it |
|---|-----------|------------------------------|
| 1 | Open/closed registry extensibility | <registry seam; router/node/models untouched> |
| 2 | Versioned, backward-compatible wire | <§6 posture> |
| 3 | DI via `Protocol`, tests need no hardware | <injected seams + fakes> |
| 4 | Stateful I/O in transports/services, not codecs | <where I/O lives; codec stays pure> |
| 5 | Config-driven, no magic numbers | <§5 config table> |
| 6 | Quality gates green; hardware glue is the only `# pragma: no cover` | <coverage floor> |
| 7 | No secrets / machine fingerprints in repo | <deploy-time `*.env`/runtime config> |
</content>
