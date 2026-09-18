from __future__ import annotations

import asyncio
import types
import typing

import anthropic
import fake_sdk_clients
import google.genai as genai
import httpx
import openai
import pytest
import sergent_py_core.model_calls as model_calls
import sergent_py_core.strict_model as core_strict_model
import sergent_py_providers.client as provider_client
import sergent_py_providers.settings as provider_settings
import sergent_py_providers.transports as provider_transports


def _request(
    model_name: str,
    *,
    thinking_effort: provider_settings.ThinkingEffort = "high",
    max_output_tokens: int | None = provider_settings._DEFAULT_MAX_OUTPUT_TOKENS,
    timeout_seconds: int | None = provider_settings._DEFAULT_TIMEOUT_SECONDS,
) -> model_calls.ModelRequest:
    return model_calls.ModelRequest(
        model_name=model_name,
        messages=[model_calls.ModelMessage(role="user", content="Return JSON.")],
        model_settings=provider_settings.ModelSettings(
            thinking_effort=thinking_effort,
            max_output_tokens=max_output_tokens,
            timeout_seconds=timeout_seconds,
        ),
        proposal_schema=fake_sdk_clients.proposal_schema(),
    )


def _invoke(provider: str, sdk_client: typing.Any, request: model_calls.ModelRequest):
    command_runner = None
    if provider == "ollama":
        command_runner = fake_sdk_clients.FakeCommandRunner(fake_sdk_clients.command_result())
    client = provider_client.LlmClient(
        sdk_clients={provider: sdk_client},
        command_runner=command_runner,
    )
    return asyncio.run(client.invoke(request))


def _ollama_response(text: str = '{"ok": true}', *, usage: object | None = None):
    return types.SimpleNamespace(
        choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=text))],
        usage=usage or types.SimpleNamespace(prompt_tokens=6, completion_tokens=7),
    )


def _gemini_sdk_request() -> httpx.Request:
    return httpx.Request(
        "POST",
        "https://generativelanguage.googleapis.com/v1beta/models/gemini:generateContent",
    )


def test_token_normalization_preserves_only_reported_counts() -> None:
    assert provider_transports._tokens(None, None) is None
    assert provider_transports._tokens(3, None) == {"input": 3}
    assert provider_transports._tokens(None, 5) == {"output": 5}
    assert provider_transports._tokens(0, 0) == {"input": 0, "output": 0}


# --- OpenAI -----------------------------------------------------------------
def test_openai_json_request_shape() -> None:
    sdk_client = fake_sdk_clients.FakeOpenAIClient(fake_sdk_clients.openai_response())
    request = _request("openai/org/gpt:experimental")
    response, payload = _invoke("openai", sdk_client, request)
    call = sdk_client.calls[0]

    assert call["model"] == "org/gpt:experimental"
    assert call["input"] == [{"role": "user", "content": "Return JSON."}]
    assert call["text"] == {
        "format": {
            "type": "json_schema",
            "name": "TestProposal",
            "schema": request.proposal_schema.json_schema,
            "strict": True,
        }
    }
    assert call["text"]["format"]["schema"] is request.proposal_schema.json_schema
    assert call["reasoning"] == {"effort": "high"}
    assert call["max_output_tokens"] == provider_settings._DEFAULT_MAX_OUTPUT_TOKENS
    assert response.raw_output == '{"ok": true}'
    assert response.parsed_json == {"ok": True}
    assert response.identity.provider == "openai"
    assert response.identity.model == "org/gpt:experimental"
    assert response.identity.sdk_package == "openai"
    assert isinstance(response.identity.sdk_version, str)
    assert len(response.attempts) == 1
    assert response.usage.request_id == "resp-openai"
    assert response.usage.tokens == {"input": 8, "output": 9}
    assert payload == {"ok": True}
    assert payload is response.parsed_json


def test_openai_forwards_cap_and_low_effort() -> None:
    low_client = fake_sdk_clients.FakeOpenAIClient(fake_sdk_clients.openai_response())
    _invoke(
        "openai",
        low_client,
        _request("openai/gpt-5.6-sol", thinking_effort="low", max_output_tokens=321),
    )
    low_call = low_client.calls[0]
    assert low_call["reasoning"] == {"effort": "low"}
    assert low_call["max_output_tokens"] == 321


def test_openai_constructed_client_uses_request_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructed: list[dict[str, typing.Any]] = []

    class CapturingOpenAIClient(fake_sdk_clients.FakeOpenAIClient):
        def __init__(self, **kwargs: typing.Any) -> None:
            constructed.append(kwargs)
            super().__init__(fake_sdk_clients.openai_response())

    monkeypatch.setenv("OPENAI_API_KEY", "key")
    monkeypatch.setattr(openai, "AsyncOpenAI", CapturingOpenAIClient)

    _invoke("openai", None, _request("openai/gpt-5.6-sol", timeout_seconds=123))

    assert constructed[0]["timeout"] == 123
    assert constructed[0]["max_retries"] == 0


def test_openai_invalid_text_response_preserves_usage() -> None:
    sdk_client = fake_sdk_clients.FakeOpenAIClient(
        types.SimpleNamespace(
            output_text="",
            output=[],
            status="completed",
            incomplete_details=None,
            id="resp-empty",
            usage=types.SimpleNamespace(input_tokens=10, output_tokens=768),
        )
    )

    with pytest.raises(model_calls.ModelError) as info:
        _invoke("openai", sdk_client, _request("openai/gpt-5.6-sol"))

    assert info.value.kind == "invalid_response"
    response = info.value.response
    assert response is not None
    assert response.usage is not None
    assert response.usage.tokens == {"input": 10, "output": 768}
    assert response.usage.request_id == "resp-empty"
    assert response.raw_output is None
    assert [attempt.status for attempt in response.attempts] == ["failure"]


def test_invalid_json_response_preserves_usage() -> None:
    sdk_client = fake_sdk_clients.FakeOpenAIClient(fake_sdk_clients.openai_response("not json"))

    with pytest.raises(model_calls.ModelError) as info:
        _invoke("openai", sdk_client, _request("openai/gpt-5.6-sol"))

    assert info.value.kind == "invalid_response"
    response = info.value.response
    assert response is not None
    assert response.usage is not None
    assert response.usage.tokens == {"input": 8, "output": 9}
    assert response.raw_output == "not json"
    assert response.parsed_json is None
    attempts = response.attempts
    assert len(attempts) == 1
    assert attempts[0].status == "success"


# --- Anthropic --------------------------------------------------------------
def test_anthropic_request_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    lowered_schema = {
        "type": "object",
        "properties": {"items": {"type": "array"}},
        "required": ["items"],
        "additionalProperties": False,
    }
    transformed: list[dict[str, typing.Any]] = []

    def transform_schema(schema: dict[str, typing.Any]) -> dict[str, typing.Any]:
        transformed.append(schema)
        return lowered_schema

    monkeypatch.setattr(anthropic, "transform_schema", transform_schema)
    sdk_client = fake_sdk_clients.FakeAnthropicClient(fake_sdk_clients.anthropic_response())
    request = model_calls.ModelRequest(
        model_name="anthropic/claude-sonnet-5",
        messages=[
            model_calls.ModelMessage(role="system", content="System prompt."),
            model_calls.ModelMessage(role="user", content="Return JSON."),
        ],
        model_settings=provider_settings.ModelSettings(),
        proposal_schema=fake_sdk_clients.proposal_schema(),
    )
    response, _ = _invoke("anthropic", sdk_client, request)
    call = sdk_client.calls[0]

    assert call["model"] == "claude-sonnet-5"
    assert call["system"] == "System prompt."
    assert call["messages"] == [{"role": "user", "content": "Return JSON."}]
    assert call["max_tokens"] == 4096
    assert call["thinking"] == {"type": "adaptive"}
    assert call["output_config"] == {
        "effort": "high",
        "format": {"type": "json_schema", "schema": lowered_schema},
    }
    assert transformed == [request.proposal_schema.json_schema]
    assert transformed[0] is request.proposal_schema.json_schema
    assert response.usage.request_id == "msg-1"
    assert response.usage.tokens == {"input": 2, "output": 3}


def test_anthropic_forwards_cap_and_low_effort() -> None:
    low_client = fake_sdk_clients.FakeAnthropicClient(fake_sdk_clients.anthropic_response())
    _invoke(
        "anthropic",
        low_client,
        _request("anthropic/claude-sonnet-5", thinking_effort="low", max_output_tokens=777),
    )
    low_call = low_client.calls[0]
    assert low_call["max_tokens"] == 777
    assert low_call["output_config"]["effort"] == "low"
    assert low_call["output_config"]["format"]["type"] == "json_schema"


def test_anthropic_retry_reuses_canonical_and_lowered_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transformed_schema = {"type": "object", "properties": {}, "additionalProperties": False}
    canonical_inputs: list[dict[str, typing.Any]] = []

    def transform_schema(schema: dict[str, typing.Any]) -> dict[str, typing.Any]:
        canonical_inputs.append(schema)
        return transformed_schema

    monkeypatch.setattr(anthropic, "transform_schema", transform_schema)
    retryable = anthropic.APIConnectionError(request=typing.cast(typing.Any, object()))
    sdk_client = fake_sdk_clients.FakeAnthropicClient(
        retryable,
        fake_sdk_clients.anthropic_response(),
    )
    request = _request("anthropic/claude-sonnet-5")

    response, _ = _invoke("anthropic", sdk_client, request)

    assert [attempt.status for attempt in response.attempts] == ["failure", "success"]
    assert canonical_inputs == [
        request.proposal_schema.json_schema,
        request.proposal_schema.json_schema,
    ]
    assert canonical_inputs[0] is canonical_inputs[1]
    first = sdk_client.calls[0]["output_config"]["format"]["schema"]
    second = sdk_client.calls[1]["output_config"]["format"]["schema"]
    assert first is transformed_schema
    assert second is first


# --- Gemini -----------------------------------------------------------------
def test_gemini_request_shape() -> None:
    sdk_client = fake_sdk_clients.FakeGeminiClient(fake_sdk_clients.gemini_response())
    request = _request("gemini/gemini-pro-latest")
    response, _ = _invoke("gemini", sdk_client, request)
    call = sdk_client.calls[0]
    contents = call["contents"]
    config = call["config"]

    assert call["model"] == "gemini-pro-latest"
    assert contents[0].role == "user"
    assert contents[0].parts[0].text == "Return JSON."
    assert config.response_mime_type == "application/json"
    assert config.response_json_schema == request.proposal_schema.json_schema
    assert config.automatic_function_calling is not None
    assert config.automatic_function_calling.disable is True
    assert config.tools is None
    assert config.max_output_tokens == provider_settings._DEFAULT_MAX_OUTPUT_TOKENS
    assert config.thinking_config is None
    assert response.usage.request_id == "gemini-1"
    assert response.usage.tokens == {"input": 4, "output": 5}


def test_gemini_constructed_client_disables_sdk_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructed: list[dict[str, typing.Any]] = []

    class CapturingGeminiClient(fake_sdk_clients.FakeGeminiClient):
        def __init__(self, **kwargs: typing.Any) -> None:
            constructed.append(kwargs)
            super().__init__(fake_sdk_clients.gemini_response())

    monkeypatch.setenv("GEMINI_API_KEY", "key")
    monkeypatch.setattr(genai, "Client", CapturingGeminiClient)

    _invoke("gemini", None, _request("gemini/gemini-pro-latest"))

    retry_options = constructed[0]["http_options"].retry_options
    assert retry_options is not None
    assert retry_options.attempts == 1


def test_gemini_forwards_cap() -> None:
    sdk_client = fake_sdk_clients.FakeGeminiClient(fake_sdk_clients.gemini_response())
    _invoke(
        "gemini",
        sdk_client,
        _request("gemini/gemini-pro-latest", max_output_tokens=512),
    )
    assert sdk_client.calls[0]["config"].max_output_tokens == 512


def test_gemini_http_timeout_is_retried_and_mapped_to_timeout_kind() -> None:
    sdk_client = fake_sdk_clients.FakeGeminiClient(
        httpx.ReadTimeout("read timed out", request=_gemini_sdk_request()),
        httpx.ReadTimeout("read timed out", request=_gemini_sdk_request()),
    )

    with pytest.raises(model_calls.ModelError) as info:
        _invoke("gemini", sdk_client, _request("gemini/gemini-pro-latest"))

    assert info.value.kind == "timeout"
    assert info.value.retryable is True
    assert info.value.response is None
    assert len(sdk_client.calls) == 2
    identity = info.value.identity
    assert identity is not None
    assert identity.provider == "gemini"
    attempts = info.value.attempts
    assert [attempt.status for attempt in attempts] == ["failure", "failure"]
    assert [attempt.retryable for attempt in attempts] == [True, True]


def test_gemini_http_connection_failure_is_retried_as_provider_unavailable() -> None:
    sdk_client = fake_sdk_clients.FakeGeminiClient(
        httpx.ConnectError("connection refused", request=_gemini_sdk_request()),
        fake_sdk_clients.gemini_response(),
    )

    response, payload = _invoke("gemini", sdk_client, _request("gemini/gemini-pro-latest"))

    assert payload == {"ok": True}
    assert len(sdk_client.calls) == 2
    assert sdk_client.calls[1] == sdk_client.calls[0]
    assert [attempt.status for attempt in response.attempts] == ["failure", "success"]
    first_error = response.attempts[0].error
    assert first_error is not None
    assert first_error.kind == "provider_unavailable"
    assert response.attempts[0].retryable is True


def test_gemini_missing_credentials() -> None:
    with pytest.raises(model_calls.ModelError) as info:
        asyncio.run(provider_client.LlmClient().invoke(_request("gemini/gemini-pro-latest")))
    assert info.value.kind == "missing_credentials"


# --- Ollama -----------------------------------------------------------------
def test_ollama_request_shape() -> None:
    sdk_client = fake_sdk_clients.FakeOllamaClient(_ollama_response())
    request = _request("ollama/gemma4:12b-it-q4_K_M")
    response, _ = _invoke("ollama", sdk_client, request)
    call = sdk_client.calls[0]

    assert call["model"] == "gemma4:12b-it-q4_K_M"
    assert call["messages"] == [{"role": "user", "content": "Return JSON."}]
    assert call["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "TestProposal",
            "schema": request.proposal_schema.json_schema,
            "strict": True,
        },
    }
    assert call["response_format"]["json_schema"]["schema"] is request.proposal_schema.json_schema
    assert call["extra_body"] == {"think": True}
    assert call["max_tokens"] == provider_settings._DEFAULT_MAX_OUTPUT_TOKENS
    assert response.parsed_json == {"ok": True}
    assert response.usage.request_id is None
    assert response.usage.tokens == {"input": 6, "output": 7}


def test_ollama_reads_native_eval_counts_when_usage_absent() -> None:
    sdk_client = fake_sdk_clients.FakeOllamaClient(
        types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=types.SimpleNamespace(content='{"ok": true}'))],
            usage=None,
            prompt_eval_count=12,
            eval_count=34,
        )
    )
    response, _ = _invoke("ollama", sdk_client, _request("ollama/gemma4:12b-it-q4_K_M"))

    assert response.usage.tokens == {"input": 12, "output": 34}


def test_ollama_forwards_cap_and_maps_common_effort() -> None:
    low_client = fake_sdk_clients.FakeOllamaClient(_ollama_response())
    _invoke(
        "ollama",
        low_client,
        _request(
            "ollama/gemma4:12b-it-q4_K_M",
            thinking_effort="low",
            max_output_tokens=64,
        ),
    )
    low_call = low_client.calls[0]
    assert low_call["extra_body"] == {"think": False}
    assert low_call["max_tokens"] == 64

    medium_client = fake_sdk_clients.FakeOllamaClient(_ollama_response())
    _invoke(
        "ollama",
        medium_client,
        _request("ollama/gemma4:12b-it-q4_K_M", thinking_effort="medium"),
    )
    assert medium_client.calls[0]["extra_body"] == {"think": True}


def test_ollama_base_url_uses_openai_compatible_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructed: list[dict[str, typing.Any]] = []

    class CapturingOpenAIClient(fake_sdk_clients.FakeOllamaClient):
        def __init__(self, **kwargs: typing.Any) -> None:
            constructed.append(kwargs)
            super().__init__(_ollama_response())

    monkeypatch.setenv("SERGENT_OLLAMA_BASE_URL", "http://host:11434/")
    monkeypatch.setattr(openai, "AsyncOpenAI", CapturingOpenAIClient)

    _invoke("ollama", None, _request("ollama/gemma4:12b-it-q4_K_M"))

    assert constructed[0]["base_url"] == "http://host:11434/v1/"
    assert constructed[0]["api_key"] == "ollama"
    assert constructed[0]["timeout"] == provider_settings._DEFAULT_TIMEOUT_SECONDS
    assert constructed[0]["max_retries"] == 0


def test_ollama_base_url_ending_in_api_rejected() -> None:
    request = _request("ollama/gemma4:12b-it-q4_K_M")
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setenv("SERGENT_OLLAMA_BASE_URL", "http://host:11434/api")
        with pytest.raises(model_calls.ModelError) as info:
            _invoke("ollama", None, request)
    assert info.value.kind == "provider_error"


# --- model_settings ownership -----------------------------------------------
def test_transport_rejects_non_model_settings() -> None:
    class OtherSettings(core_strict_model.StrictModel):
        value: int = 1

    sdk_client = fake_sdk_clients.FakeOpenAIClient(fake_sdk_clients.openai_response())
    selection = provider_client._select_model("openai/gpt-5.6-sol")
    request = model_calls.ModelRequest(
        model_name="openai/gpt-5.6-sol",
        messages=[model_calls.ModelMessage(role="user", content="Return JSON.")],
        model_settings=OtherSettings(),
        proposal_schema=fake_sdk_clients.proposal_schema(),
    )
    with pytest.raises(model_calls.ModelError) as info:
        asyncio.run(provider_transports._run_call(selection, request, sdk_client=sdk_client))
    assert info.value.kind == "provider_error"
    assert sdk_client.calls == []
