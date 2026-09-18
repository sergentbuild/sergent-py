from __future__ import annotations

import asyncio

import fake_sdk_clients
import pydantic
import pytest
import sergent_py_core.model_calls as model_calls
import sergent_py_providers.settings as provider_settings
import sergent_py_providers.testing as provider_testing


class CannedOutput(pydantic.BaseModel):
    value: int


def _request(model_name: str = "openai/gpt-5.6-sol") -> model_calls.ModelRequest:
    return model_calls.ModelRequest(
        model_name=model_name,
        messages=[model_calls.ModelMessage(role="user", content="hi")],
        model_settings=provider_settings.ModelSettings(),
        proposal_schema=fake_sdk_clients.proposal_schema(),
    )


def test_static_resolves_full_name_and_fixed_fields() -> None:
    client = provider_testing.StaticLlmClient([CannedOutput(value=5)])
    response, payload = asyncio.run(client.invoke(_request("anthropic/claude/team/sonnet:5   ")))
    assert (response.identity.provider, response.identity.model) == (
        "anthropic",
        "claude/team/sonnet:5   ",
    )
    assert response.identity.sdk_package == "anthropic"
    assert isinstance(response.identity.sdk_version, str)
    assert response.usage.latency_ms == 7
    assert response.usage.tokens == {"input": 11, "output": 13}
    assert response.usage.request_id == "static-provider-request"
    assert payload == {"value": 5}
    assert payload is response.parsed_json
    assert response.raw_output == '{"value":5}'
    assert response.parsed_json == {"value": 5}
    attempts = response.attempts
    assert len(attempts) == 1
    assert attempts[0].status == "success"


def test_static_records_requests_and_fifo() -> None:
    client = provider_testing.StaticLlmClient([{"value": 1}, CannedOutput(value=2)])
    first_request = _request()
    _, first = asyncio.run(client.invoke(first_request))
    _, second = asyncio.run(client.invoke(_request()))
    assert (first["value"], second["value"]) == (1, 2)
    assert len(client.requests) == 2
    assert all(isinstance(r, model_calls.ModelRequest) for r in client.requests)
    assert client.requests[0].proposal_schema is first_request.proposal_schema


def test_static_no_outputs_raises() -> None:
    client = provider_testing.StaticLlmClient()
    with pytest.raises(model_calls.ModelError) as info:
        asyncio.run(client.invoke(_request()))
    assert info.value.kind == "invalid_response"
    identity = info.value.identity
    assert identity is not None
    assert identity.provider == "openai"
    assert identity.model == "gpt-5.6-sol"
    assert len(info.value.attempts) == 1


@pytest.mark.parametrize(
    "output",
    [["value"], object()],
    ids=["array", "non-serializable-object"],
)
def test_static_rejects_a_non_object_json_value(output: object) -> None:
    client = provider_testing.StaticLlmClient([output])

    with pytest.raises(model_calls.ModelError) as info:
        asyncio.run(client.invoke(_request()))

    assert info.value.kind == "invalid_response"
    assert info.value.response is not None
    assert info.value.response.raw_output is None
    assert info.value.response.parsed_json is None


def test_static_ollama_selection_never_runs_preflight_or_sdk_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def denied_command(*args: object, **kwargs: object) -> None:
        raise AssertionError("StaticLlmClient must not run local commands")

    monkeypatch.setattr(
        asyncio,
        "create_subprocess_exec",
        denied_command,
    )
    client = provider_testing.StaticLlmClient([{"ok": True}])

    response, payload = asyncio.run(client.invoke(_request("ollama/org/model:latest")))

    assert response.identity.provider == "ollama"
    assert response.identity.model == "org/model:latest"
    assert response.identity.sdk_package == "openai"
    assert payload == {"ok": True}


@pytest.mark.parametrize(
    ("model_name", "kind"),
    [("model", "invalid_model_name"), ("unknown/model", "unknown_provider")],
)
def test_static_uses_the_same_local_selection_errors(model_name: str, kind: str) -> None:
    client = provider_testing.StaticLlmClient([{"ok": True}])

    with pytest.raises(model_calls.ModelError) as info:
        asyncio.run(client.invoke(_request(model_name)))

    assert info.value.kind == kind
    assert len(client.requests) == 1
