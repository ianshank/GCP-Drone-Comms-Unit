# Initiative E — AI Inference (`meshsa.inference`)

> **Status: Implemented (MVP + HTTP-transport seam); Track-B hardening is Definition.**
> (Definition → Implemented → Validated; see [README.md](README.md).) Pairs with
> [../CHARTER.md](../CHARTER.md) §4 (invariants), [../ROADMAP.md](../ROADMAP.md) Initiative E,
> and [../IMPLEMENTATION_PLAN.md](../IMPLEMENTATION_PLAN.md) Track B. Code cites this spec by `§`.

**Initiative:** E  **Track:** B  **Authored:** 2026-06-30 (back-fills the shipped MVP)

---

## 1. Scope

An optional, async bridge that subscribes to mesh Router traffic, sends messages to NVIDIA's
OpenAI-compatible Nemotron NIM API for tactical analysis, and broadcasts `[AI Insight]`
summaries back onto the mesh. Installed with `meshsa[inference]`; the base install is unaffected.

Deliverables:

1. **MVP (shipped):** `NemotronClient`, `InferenceService`, `NemotronConfig`, `InferenceResult`;
   `MESHSA_INFERENCE_*` env bindings; lazy `aiohttp`, session reuse, feedback-loop prevention,
   lifecycle guards, configurable backoff, injectable sleep.
2. **HTTP-transport seam (shipped, §3/§5):** the network boundary is an injectable
   `HttpTransport` `Protocol` so the retry/parse logic is pure and version-independent.
3. **Hardening backlog (Definition, §4/§7):** local rate limiting, structured response parsing,
   multi-model support, offline fallback.

### Non-goals

- The LLM/inference layer never issues vehicle commands (CHARTER §3; Initiative C §6). It
  observes and summarizes only.
- No new wire `MessageKind`: insights ride existing `CHAT` envelopes.

---

## 2. Facts the implementation relies on

- The NIM endpoint is OpenAI-compatible: `POST {base_url}/chat/completions`, bearer auth,
  success body `{"choices": [{"message": {"content": "..."}}]}`.
- `429` signals rate limiting (retry with backoff); other non-2xx are errors.
- Multi-node feedback loops are prevented by an `insight_prefix` marker on emitted messages.

---

## 3. Architecture

```
Router ── subscribe ──▶ InferenceService.handle_message
                              │ (skips own-source + insight-prefixed msgs)
                              ▼
                       NemotronClient.analyze   ── pure retry/backoff/parse (§5)
                              │
                       HttpTransport.post_json  ── injectable seam (§5)
                              │
              AiohttpTransport (default)        ── the only socket glue; owns the
              │ reused aiohttp.ClientSession      session + asyncio.Lock; maps errors
              ▼
            NVIDIA NIM API
```

The stateful HTTP I/O lives in the transport, not the client (CHARTER §4.4). The client is a
pure state machine over `HttpResponse`/`InferenceTransportError` and is fully fakeable
(CHARTER §4.3) — unit tests need no `aiohttp` and no sockets.

---

## 4. Behaviour / state model

`analyze()` retry loop (config-driven, no literals):

- **Transport error** (`InferenceTransportError` from timeout/connection): retry up to
  `max_retries`; on exhaustion, re-raise.
- **HTTP 429 / 5xx (transient):** retry while `attempt < max_retries`; on exhaustion **fail
  closed** with `InferenceHttpError(status)`.
- **Other 4xx (e.g. 401 bad key — not transient):** **fail fast** with `InferenceHttpError(status)`
  immediately; do not consume the retry budget.
- **Backoff:** `min(backoff_base**attempt, backoff_max_s)` via the injectable `sleep` — capped to
  avoid unbounded waits / thundering-herd.
- **2xx:** parse `choices[0].message.content`; a malformed/empty body raises **`InferenceError`**
  ("malformed completion payload"), not a raw `KeyError`/`IndexError`, and is **not** retried (a
  bad shape is not a transient fault).

Service: own-source messages and `insight_prefix`-prefixed messages are dropped (feedback-loop
prevention); analysis runs in a tracked background task; cancellation propagates, other failures
are logged and swallowed (one bad message never tears down the service).

---

## 5. Module specifications

`inference.py`:

- `HttpResponse(status: int, payload: dict)` — frozen.
- `HttpTransport` (`Protocol`, runtime-checkable): `post_json(url, *, headers, json_body,
  timeout_s) -> HttpResponse`; `aclose()`. Implementations map native failures to
  `InferenceTransportError`.
- `AiohttpTransport` — default; lazy `aiohttp`, reused session under `asyncio.Lock`, maps native
  errors to the neutral model. Takes an injectable `session_factory` so the reuse/lock/error-map
  logic is unit-tested; only real `aiohttp.ClientSession()` construction is `# pragma: no cover`.
- `NemotronClient(config, *, sleep=asyncio.sleep, transport=None)` — pure logic; default
  transport is `AiohttpTransport`.
- `InferenceService(..., *, transport=None)`; `build_node(..., inference_transport=None)`.

### Config (`NemotronConfig`, env prefix `MESHSA_INFERENCE_`)

| Field | Default | Meaning |
| ----- | ------- | ------- |
| `enabled` | `False` | master switch |
| `api_key` | `""` | bearer credential (deploy-time, never committed) |
| `base_url` | `https://integrate.api.nvidia.com/v1` | NIM endpoint |
| `model` | `nvidia/nemotron-…` | model id |
| `system_prompt` | tactical-summary prompt | system role text |
| `temperature` / `max_tokens` | `0.6` / `512` | sampling |
| `timeout_s` | `30.0` | per-request timeout |
| `max_retries` | `3` | retry budget (429/5xx/transport only) |
| `backoff_base` | `2.0` (`>= 1.0`) | `delay = backoff_base**attempt` |
| `backoff_max_s` | `30.0` (`>= 0.0`) | cap applied as `min(backoff_base**attempt, backoff_max_s)` |
| `insight_prefix` | `[AI Insight]` (`min_length 1`) | feedback-loop marker |

**Track-B additions (Definition):** `min_interval_s`, `max_concurrent_requests` (rate limiting);
a `response_format`/JSON-mode toggle (structured parsing); a model allow-list (multi-model); an
offline queue bound (offline fallback). Each is a config field with an explicit default + env
binding — no literals.

---

## 6. Wire / schema posture

**N/A / additive.** Insights ride existing `CHAT` envelopes; no `SCHEMA_VERSION` change. The
`HttpTransport` seam is an internal API addition (new optional `transport=` params, default
preserves prior behavior) — backwards-compatible, no wire impact.

---

## 7. Test plan (by category)

Fakes-first; **no `aiohttp`/sockets in unit tests** (a `FakeHttpTransport` injected via the
`make_transport` fixture). Coverage floor: `inference.py` 100% line+branch (achieved).

- **Unit:** success; disabled/no-key short-circuit; 429 retry→recover; persistent 429 →
  `InferenceHttpError(429)`; 5xx raise + 5xx retried-then-raised; transport error retry/raise;
  malformed/empty body → `KeyError`/`IndexError` (no retry); injectable sleep + `backoff_base`
  exponent; `close()` delegates to transport; cancellation propagates; `Protocol` conformance.
- **Integration/e2e:** mesh inbound → analysis → mesh outbound (`build_node(inference_transport=…)`)
  with feedback-loop + own-source suppression.
- **Security:** missing api-key path; bearer header shape; never log the key.

> **Test-harness note (Track 0.1):** the boundary is mocked at the `HttpTransport` seam, never
> at `aiohttp` internals — this is why the suite is immune to `aiohttp` version drift. Do **not**
> reintroduce `aioresponses`.

---

## 8. Exit criteria

- **Mechanism (met):** §7 green; `ruff`/`ruff format`/`mypy --strict`/`pytest` green;
  `inference.py` at 100%; CHANGELOG + NEXTSTEPS updated.
- **Validation (pending, Track 1/field):** a live field run against the real NIM API relaying a
  Meshtastic `CHAT` summary to ATAK/FreeTAKServer moves status → `Validated`.

---

## 9. CHARTER §4 invariant checklist

| # | Invariant | How preserved |
|---|-----------|---------------|
| 1 | Open/closed registry | Inference is an additive optional service; router/node/models untouched (only an optional `inference_transport=` param added to `build_node`). |
| 2 | Versioned, backward-compatible wire | No `MessageKind`/schema change; insights use `CHAT` (§6). |
| 3 | DI via `Protocol`, no hardware in tests | `HttpTransport`/`sleep` injected; unit tests use a pure fake. |
| 4 | Stateful I/O in transports, not pure logic | Session reuse/error-mapping live in `AiohttpTransport`; the client is pure. |
| 5 | Config-driven, no magic numbers | All operational values are `NemotronConfig` fields with env bindings (§5). |
| 6 | Quality gates; glue is the only `# pragma: no cover` | Only `AiohttpTransport`'s socket I/O is pragma'd; 100% elsewhere. |
| 7 | No secrets in repo | `api_key` is deploy-time (`MESHSA_INFERENCE_API_KEY`), never committed. |
