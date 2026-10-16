# MeshSA Core Agent Guide

> Scope: `packages/meshsa/src/meshsa` · Parent: [../../AGENTS.md](../../AGENTS.md)

## Traps

- **`build_node()` skips unknown transport types on purpose** and logs a warning. It
  looks like a bug and is forward-compatible config loading; converting it to a hard
  failure breaks every node whose config names a transport this build lacks.
- **`defaults.py` is the only home for port, host, queue and backoff literals.** It
  imports nothing from `meshsa`, deliberately. `literal_guard` rejects a re-typed literal
  elsewhere, so adding one here is a CI failure, not a style note.
- **`netauth.validate_bind` guards on `not token`, not `token is None`.** An empty string
  is *not* a token. A re-implementation using the weaker predicate has shipped here
  before; see `docs/AUDIT_M2_AUTH.md` for the surface it exposed.
- **`Router` splits decode failures into two counters** (`schema_mismatch` vs
  `dropped_undecodable`). Collapsing them into one `except` loses the signal that
  distinguishes a version skew from a corrupt frame.
- **`UNKNOWN_ERROR_M` is shared** between `models.py` and the CoT codec. One value, two
  readers.

### `command/` (frozen)

`packages/meshsa/src/meshsa/command/` cannot hold its own guide: it is inside
`command_emission_globs`, and `match_globs` uses `fnmatch`, so the scope-freeze hook
denies a write to `command/AGENTS.md` exactly as it denies one to `lifecycle.py`.
Its traps live here instead. The ACK policy is fail-closed and must not be relaxed:
`DENIED`/`UNSUPPORTED`/`FAILED`/`CANCELLED` are terminal with no retry. `JsonlAuditLog`
fsyncs synchronously and must not run on the loop thread. The `literal_guard` `"*"`
exception on `command/config.py` is deliberate *because* the zone is frozen — do not
"fix" those literals.

## Rules

- Register transports and codecs through `registry.py`, never by editing router or node —
  why: a new medium must not require touching shared contract code.
- Keep operational values in Pydantic config, not in transport logic — why: `defaults.py`
  plus config is the single source `literal_guard` enforces. — control: literal_guard
- Route every listener through `netauth.validate_bind` — why: it is the sole audited bind
  primitive and CI scans for it. — control: bind_guard
- Do not edit anything under `command/` — why: the M2 gate is unmet.
  — control: scope_freeze
- Bump `version.py` with any envelope shape change, and update tests, docs and
  `CHANGELOG.md` together — why: every wire envelope carries `schema_version` and a silent
  shape change strands old readers.

## Subagents

- `security-reviewer` — mandatory before any PR touching this folder.
- `bind-auditor` — any diff adding, moving, or removing a socket bind.
- `config-guardian` — before adding any port, host, or interval literal.
- `charter-gate-keeper` — any attempt to touch or enable the command path.
- `meshsa-schema-version-bump` — the skill to follow when the envelope shape changes.
