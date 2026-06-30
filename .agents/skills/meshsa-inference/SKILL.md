---
name: meshsa-inference
description: "Use when: working on the optional NVIDIA Nemotron inference bridge — meshsa.inference, NemotronClient/InferenceService/NemotronConfig, MESHSA_INFERENCE_* env vars, aiohttp session reuse, [AI Insight] feedback-loop filter, or the aioresponses test mocks."
argument-hint: "The inference change (rate-limit, structured parse, multi-model, offline, mocks)"
---

# MeshSA Inference (Nemotron bridge)

Optional, async AI bridge: subscribes to mesh traffic → NVIDIA Nemotron NIM → `[AI Insight]`
summaries back on the mesh. Install with `meshsa[inference]`. Keep the base install unaffected.

## When to Use

- Editing `meshsa.inference` or its config bindings, or the inference tests.
- Working the backlog: local rate limiting, structured response parsing, multi-model, offline
  fallback (plan Track B; spec `docs/specs/initiative-e-inference.md`).

## Invariants to preserve

1. **Lazy `aiohttp` import** (`_require_aiohttp()` guard) so `import meshsa` and the base install
   stay light. The `inference` extra owns the dependency.
2. **`aiohttp.ClientSession` reuse under the existing `asyncio.Lock`** — not per-call; the lock
   guards creation, use, and close.
3. **Feedback-loop prevention:** messages prefixed with the configurable `insight_prefix`
   (`[AI Insight]`) are never re-analyzed.
4. **Lifecycle guards** (`_running`/`_subscribed`) and **configurable backoff** (`backoff_base`)
   with an **injectable `sleep`** for deterministic tests.
5. **Config-driven:** all `NemotronConfig` fields are settable via `MESHSA_INFERENCE_*` env vars
   with the standard precedence. New tunables (e.g. `min_interval_s`, `max_concurrent_requests`)
   are config fields with explicit defaults + env bindings — no literals.

## HTTP boundary (injectable transport — do not reintroduce aioresponses)

The network boundary is the injectable **`HttpTransport`** `Protocol` (`HttpResponse` + default
socket-backed `AiohttpTransport`). The pure retry/backoff/parse logic lives in `NemotronClient`;
the `asyncio.Lock`-guarded session reuse + error mapping live in `AiohttpTransport` (the only
socket glue — testable via its injectable `session_factory`). **Unit-test against a fake**
(`FakeHttpTransport` via the `make_transport` fixture) — never mock `aiohttp` internals. The old
`aioresponses` mock coupled to `aiohttp` internals and broke on version drift; it and the
`aiohttp<3.10` pin were removed (plan Track 0.1). Behaviour to preserve: non-429 4xx fail fast;
429/5xx retry with **capped** backoff (`backoff_base`/`backoff_max_s`); failures surface as
`InferenceTransportError`/`InferenceHttpError`; a malformed body raises `InferenceError`.

## Gates

Run from `packages/meshsa` with the extra installed
(`pip install -e ".[dev,inference]"`): `python -m pytest`, `mypy src`, `ruff check .`,
`ruff format --check .`. Keep `inference.py` at ~99% line+branch.

## References

- `packages/meshsa/src/meshsa/inference.py`, `config.py` (`MESHSA_INFERENCE_*` bindings)
- `packages/meshsa/tests/test_inference.py`, `test_inference_e2e.py`
- `docs/specs/initiative-e-inference.md` (author from TEMPLATE before Track B work)
