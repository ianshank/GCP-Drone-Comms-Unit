"""``meshsa.inference.client`` tests: NemotronClient's retry/backoff/parse logic,
exercised via an injected ``FakeHttpTransport`` (the ``make_transport`` fixture) —
pure, no ``aiohttp`` and no sockets — so these tests are independent of any
``aiohttp`` version.
"""

import pytest

from meshsa import (
    Envelope,
    HttpResponse,
    HttpTransport,
    InferenceError,
    InferenceHttpError,
    InferenceTransportError,
    MessageKind,
    NemotronClient,
    NemotronConfig,
)


def _ok(content: str) -> HttpResponse:
    """A 200 response shaped like the NIM chat-completions payload."""
    return HttpResponse(status=200, payload={"choices": [{"message": {"content": content}}]})


async def _noop_sleep(_delay: float) -> None:
    """A sleep that records nothing and never yields wall-clock time."""


@pytest.fixture
def env():
    return Envelope(
        schema_version=1,
        msg_id="msg-1",
        ts=1.0,
        source_uid="node-a",
        kind=MessageKind.PLI,
        payload={"position": {"lat": 1.0, "lon": 2.0}},
    )


async def test_nemotron_client_success(make_transport, env):
    cfg = NemotronConfig(enabled=True, api_key="nvapi-test")
    transport = make_transport([_ok("Test summary")])
    client = NemotronClient(cfg, transport=transport)

    result = await client.analyze(env)
    assert result.summary == "Test summary"
    # Request shape: signed bearer header + chat-completions endpoint.
    call = transport.calls[0]
    assert call["url"].endswith("/chat/completions")
    assert call["headers"]["Authorization"] == "Bearer nvapi-test"
    assert call["timeout_s"] == cfg.timeout_s


async def test_nemotron_client_satisfies_protocol(make_transport):
    # The fake is a structural HttpTransport (runtime-checkable Protocol).
    assert isinstance(make_transport([]), HttpTransport)


async def test_nemotron_client_disabled(make_transport, env):
    cfg = NemotronConfig(enabled=False)
    transport = make_transport([])
    client = NemotronClient(cfg, transport=transport)
    result = await client.analyze(env)
    assert result.summary == ""
    assert transport.calls == []  # short-circuits before any HTTP call


async def test_nemotron_client_retry_on_429(make_transport, env):
    cfg = NemotronConfig(enabled=True, api_key="nvapi-test", max_retries=1)
    transport = make_transport([HttpResponse(status=429, payload={}), _ok("Recovered")])
    client = NemotronClient(cfg, sleep=_noop_sleep, transport=transport)

    result = await client.analyze(env)
    assert result.summary == "Recovered"
    assert len(transport.calls) == 2


async def test_nemotron_client_persistent_429_raises(make_transport, env):
    cfg = NemotronConfig(enabled=True, api_key="nvapi-test", max_retries=1)
    transport = make_transport([HttpResponse(status=429, payload={}) for _ in range(2)])
    client = NemotronClient(cfg, sleep=_noop_sleep, transport=transport)

    with pytest.raises(InferenceHttpError) as exc:
        await client.analyze(env)
    assert exc.value.status == 429
    assert len(transport.calls) == 2


async def test_nemotron_client_timeout_propagates(make_transport, env):
    cfg = NemotronConfig(enabled=True, api_key="nvapi-test", timeout_s=0.1, max_retries=0)
    transport = make_transport([InferenceTransportError("timed out")])
    client = NemotronClient(cfg, transport=transport)

    with pytest.raises(InferenceTransportError):
        await client.analyze(env)


async def test_nemotron_client_transport_error_propagates(make_transport, env):
    """A transport error on the final attempt must propagate after logging."""
    cfg = NemotronConfig(enabled=True, api_key="nvapi-test", max_retries=0)
    transport = make_transport([InferenceTransportError("connection reset")])
    client = NemotronClient(cfg, transport=transport)

    with pytest.raises(InferenceTransportError):
        await client.analyze(env)


async def test_close_delegates_to_transport(make_transport):
    cfg = NemotronConfig(enabled=True, api_key="nvapi-test")
    transport = make_transport([])
    client = NemotronClient(cfg, transport=transport)
    await client.close()
    assert transport.closed is True


async def test_nemotron_client_no_api_key_returns_empty(make_transport, env):
    """When api_key is empty but enabled is True, analyze returns empty result."""
    cfg = NemotronConfig(enabled=True, api_key="")
    client = NemotronClient(cfg, transport=make_transport([]))
    result = await client.analyze(env)
    assert result.summary == ""
    assert result.raw_response == ""


# ── Server error and malformed response tests ───────────────────────────


async def test_nemotron_client_500_error_raises(make_transport, env):
    """5xx server errors should propagate as InferenceHttpError carrying the status."""
    cfg = NemotronConfig(enabled=True, api_key="nvapi-test", max_retries=0)
    transport = make_transport([HttpResponse(status=500, payload={})])
    client = NemotronClient(cfg, transport=transport)

    with pytest.raises(InferenceHttpError) as exc:
        await client.analyze(env)
    assert exc.value.status == 500


async def test_nemotron_client_500_retried_then_raised(make_transport, env):
    """A retryable 5xx is retried up to the budget, then fails closed."""
    cfg = NemotronConfig(enabled=True, api_key="nvapi-test", max_retries=1)
    transport = make_transport([HttpResponse(status=500, payload={}) for _ in range(2)])
    client = NemotronClient(cfg, sleep=_noop_sleep, transport=transport)

    with pytest.raises(InferenceHttpError) as exc:
        await client.analyze(env)
    assert exc.value.status == 500
    assert len(transport.calls) == 2  # one initial + one retry


async def test_nemotron_client_malformed_json_maps_to_inference_error(make_transport, env):
    """A 200 body missing 'choices' fails as InferenceError, not a raw KeyError (no retry)."""
    cfg = NemotronConfig(enabled=True, api_key="nvapi-test", max_retries=0)
    transport = make_transport([HttpResponse(status=200, payload={"error": "unexpected"})])
    client = NemotronClient(cfg, transport=transport)

    with pytest.raises(InferenceError):
        await client.analyze(env)
    assert len(transport.calls) == 1  # a malformed body is not transient — no retry


async def test_nemotron_client_empty_choices_maps_to_inference_error(make_transport, env):
    """An empty 'choices' array fails as InferenceError, not a raw IndexError."""
    cfg = NemotronConfig(enabled=True, api_key="nvapi-test", max_retries=0)
    transport = make_transport([HttpResponse(status=200, payload={"choices": []})])
    client = NemotronClient(cfg, transport=transport)

    with pytest.raises(InferenceError):
        await client.analyze(env)


async def test_nemotron_client_4xx_fails_fast(make_transport, env):
    """A non-429 4xx (e.g. 401 bad key) fails immediately — it must not burn the retry budget."""
    cfg = NemotronConfig(enabled=True, api_key="bad-key", max_retries=3)
    transport = make_transport([HttpResponse(status=401, payload={}) for _ in range(4)])
    client = NemotronClient(cfg, sleep=_noop_sleep, transport=transport)

    with pytest.raises(InferenceHttpError) as exc:
        await client.analyze(env)
    assert exc.value.status == 401
    assert len(transport.calls) == 1  # fail fast: exactly one attempt


async def test_nemotron_client_backoff_is_capped(make_transport, env):
    """Backoff delay is clamped to backoff_max_s rather than growing unbounded."""
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    cfg = NemotronConfig(
        enabled=True, api_key="nvapi-test", max_retries=3, backoff_base=10.0, backoff_max_s=5.0
    )
    transport = make_transport(
        [HttpResponse(status=503, payload={}) for _ in range(3)] + [_ok("ok")]
    )
    client = NemotronClient(cfg, sleep=fake_sleep, transport=transport)

    result = await client.analyze(env)
    assert result.summary == "ok"
    # 10**0=1.0, then 10**1 and 10**2 are clamped to 5.0
    assert sleeps == [1.0, 5.0, 5.0]


async def test_nemotron_client_uses_injectable_sleep_and_backoff_base(make_transport, env):
    """Custom sleep and backoff_base should be used during 429 retries."""
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    cfg = NemotronConfig(enabled=True, api_key="nvapi-test", max_retries=2, backoff_base=3.0)
    transport = make_transport(
        [HttpResponse(status=429, payload={}), HttpResponse(status=429, payload={}), _ok("Finally")]
    )
    client = NemotronClient(cfg, sleep=fake_sleep, transport=transport)

    result = await client.analyze(env)
    assert result.summary == "Finally"
    # backoff_base=3.0: sleep(3**0)=1.0, sleep(3**1)=3.0
    assert sleeps == [1.0, 3.0]


async def test_nemotron_client_injectable_sleep_on_transient_error(make_transport, env):
    """Injectable sleep should be used during transient error retries too."""
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    cfg = NemotronConfig(enabled=True, api_key="nvapi-test", max_retries=1, backoff_base=2.0)
    transport = make_transport([InferenceTransportError("transient"), _ok("OK")])
    client = NemotronClient(cfg, sleep=fake_sleep, transport=transport)

    result = await client.analyze(env)
    assert result.summary == "OK"
    # backoff_base=2.0: sleep(2**0)=1.0
    assert sleeps == [1.0]


# ── Track-B: structured (JSON) response parsing ─────────────────────────


async def test_client_guided_json_sends_nvext_and_extracts_summary(make_transport, env):
    """A guided_json_schema is sent as nvext.guided_json and a JSON reply is unwrapped."""
    cfg = NemotronConfig(enabled=True, api_key="k", guided_json_schema='{"type": "object"}')
    transport = make_transport([_ok('{"summary": "structured reply"}')])
    client = NemotronClient(cfg, transport=transport)

    result = await client.analyze(env)
    assert result.summary == "structured reply"
    body = transport.calls[0]["json_body"]
    assert body["nvext"] == {"guided_json": {"type": "object"}}
    assert "response_format" not in body  # schema wins; the portable toggle is not sent


async def test_client_response_format_json_sends_toggle_and_extracts(make_transport, env):
    """response_format='json' (no schema) sends the portable OpenAI JSON toggle."""
    cfg = NemotronConfig(enabled=True, api_key="k", response_format="json")
    transport = make_transport([_ok('{"summary": "hi"}')])
    client = NemotronClient(cfg, transport=transport)

    result = await client.analyze(env)
    assert result.summary == "hi"
    body = transport.calls[0]["json_body"]
    assert body["response_format"] == {"type": "json_object"}
    assert "nvext" not in body


async def test_client_json_mode_falls_back_to_raw_on_non_json(make_transport, env):
    """A structured request whose reply is not JSON keeps the raw text (never lost)."""
    cfg = NemotronConfig(enabled=True, api_key="k", response_format="json")
    client = NemotronClient(cfg, transport=make_transport([_ok("just prose")]))
    result = await client.analyze(env)
    assert result.summary == "just prose"


async def test_client_json_mode_dict_without_summary_keeps_raw(make_transport, env):
    """A JSON object lacking a string 'summary' field falls back to the raw content."""
    cfg = NemotronConfig(enabled=True, api_key="k", response_format="json")
    client = NemotronClient(cfg, transport=make_transport([_ok('{"other": 1}')]))
    result = await client.analyze(env)
    assert result.summary == '{"other": 1}'


async def test_client_text_mode_sends_no_structured_directive(make_transport, env):
    """The default text mode sends neither nvext nor response_format."""
    cfg = NemotronConfig(enabled=True, api_key="k")
    transport = make_transport([_ok("plain")])
    client = NemotronClient(cfg, transport=transport)
    await client.analyze(env)
    body = transport.calls[0]["json_body"]
    assert "nvext" not in body and "response_format" not in body


async def test_client_guided_json_summary_field_is_configurable(make_transport, env):
    """The unwrap key follows guided_json_summary_field, not a hardcoded 'summary'."""
    cfg = NemotronConfig(
        enabled=True,
        api_key="k",
        guided_json_schema='{"type": "object"}',
        guided_json_summary_field="report",
    )
    transport = make_transport([_ok('{"report": "custom-key reply", "summary": "ignored"}')])
    client = NemotronClient(cfg, transport=transport)
    result = await client.analyze(env)
    assert result.summary == "custom-key reply"


async def test_client_json_mode_missing_configured_field_falls_back(make_transport, env):
    """When the configured field is absent, fall back to raw text (never lose the reply)."""
    cfg = NemotronConfig(
        enabled=True, api_key="k", response_format="json", guided_json_summary_field="report"
    )
    client = NemotronClient(cfg, transport=make_transport([_ok('{"summary": "wrong key"}')]))
    result = await client.analyze(env)
    assert result.summary == '{"summary": "wrong key"}'
