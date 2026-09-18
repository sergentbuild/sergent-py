from __future__ import annotations

import asyncio
import types
import typing

import fake_sdk_clients
import pytest
import sergent_py_core.model_calls as model_calls
import sergent_py_providers.client as provider_client
import sergent_py_providers.settings as provider_settings


def _request(model_name: str) -> model_calls.ModelRequest:
    return model_calls.ModelRequest(
        model_name=model_name,
        messages=[model_calls.ModelMessage(role="user", content="Return JSON.")],
        model_settings=provider_settings.ModelSettings(),
        proposal_schema=fake_sdk_clients.proposal_schema(),
    )


def _invoke(provider: str, sdk_client: typing.Any, request: model_calls.ModelRequest):
    client = provider_client.LlmClient(sdk_clients={provider: sdk_client})
    return asyncio.run(client.invoke(request))


@pytest.mark.parametrize("reason", ["max_output_tokens", "content_filter"])
def test_openai_incomplete_envelope_is_non_retryable_with_partial_evidence(
    reason: str,
) -> None:
    sdk_client = fake_sdk_clients.FakeOpenAIClient(
        fake_sdk_clients.openai_response(
            '{"partial":true}',
            status="incomplete",
            incomplete_reason=reason,
        )
    )

    with pytest.raises(model_calls.ModelError) as info:
        _invoke("openai", sdk_client, _request("openai/gpt-5.6-sol"))

    assert info.value.kind == "invalid_response"
    assert info.value.retryable is False
    assert reason in info.value.message
    response = info.value.response
    assert response is not None
    assert response.identity.provider == "openai"
    assert response.usage.tokens == {"input": 8, "output": 9}
    assert response.raw_output == '{"partial":true}'
    assert response.parsed_json is None
    assert [attempt.status for attempt in response.attempts] == ["failure"]
    assert len(sdk_client.calls) == 1


def test_openai_refusal_envelope_is_non_retryable_with_refusal_evidence() -> None:
    refusal = types.SimpleNamespace(type="refusal", refusal="Cannot assist with that.")
    message = types.SimpleNamespace(type="message", content=[refusal])
    sdk_client = fake_sdk_clients.FakeOpenAIClient(
        fake_sdk_clients.openai_response("", output=[message])
    )

    with pytest.raises(model_calls.ModelError) as info:
        _invoke("openai", sdk_client, _request("openai/gpt-5.6-sol"))

    assert info.value.kind == "invalid_response"
    assert info.value.retryable is False
    assert "Cannot assist with that." in info.value.message
    response = info.value.response
    assert response is not None
    assert response.identity.provider == "openai"
    assert response.usage.request_id == "resp-openai"
    assert response.raw_output == "Cannot assist with that."
    assert response.parsed_json is None
    assert [attempt.status for attempt in response.attempts] == ["failure"]
    assert len(sdk_client.calls) == 1


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
def test_anthropic_failure_envelope_is_non_retryable_with_partial_evidence(
    stop_reason: str,
) -> None:
    sdk_client = fake_sdk_clients.FakeAnthropicClient(
        fake_sdk_clients.anthropic_response(
            '{"partial":true}',
            stop_reason=stop_reason,
        )
    )

    with pytest.raises(model_calls.ModelError) as info:
        _invoke("anthropic", sdk_client, _request("anthropic/claude-sonnet-5"))

    assert info.value.kind == "invalid_response"
    assert info.value.retryable is False
    assert stop_reason in info.value.message or stop_reason == "refusal"
    response = info.value.response
    assert response is not None
    assert response.identity.provider == "anthropic"
    assert response.usage.tokens == {"input": 2, "output": 3}
    assert response.raw_output == '{"partial":true}'
    assert response.parsed_json is None
    assert [attempt.status for attempt in response.attempts] == ["failure"]
    assert len(sdk_client.calls) == 1
