from __future__ import annotations

import asyncio
import typing

import anthropic
import pytest

import fake_sdk_clients
import sergent_py_core.model_calls as model_calls
import sergent_py_core.proposals.schema as proposal_schema
import sergent_py_core.strict_model as strict_model
import sergent_py_providers.client as provider_client
import sergent_py_providers.settings as provider_settings


def test_pinned_anthropic_sdk_lowers_the_shared_canonical_schema() -> None:
    """Pin the documented lowering used by the raw Messages request adapter."""
    canonical = fake_sdk_clients.proposal_schema().json_schema

    lowered = anthropic.transform_schema(canonical)

    assert lowered == {
        "$defs": {
            "Choice": {
                "type": "object",
                "properties": {
                    "value": {
                        "type": "integer",
                        "description": "{minimum: 1, maximum: 3}",
                    }
                },
                "additionalProperties": False,
                "required": ["value"],
            }
        },
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {"$ref": "#/$defs/Choice"},
                "minItems": 1,
                "description": "{maxItems: 2}",
            }
        },
        "additionalProperties": False,
        "required": ["items"],
    }
    assert lowered is not canonical


class MixedEnumProposal(strict_model.StrictModel):
    value: typing.Literal[1, "auto"]


def test_unlowerable_canonical_schema_is_contained_as_invalid_payload() -> None:
    """A construction-valid schema the pinned SDK rejects fails as one typed error."""
    request = model_calls.ModelRequest(
        model_name="anthropic/claude-sonnet-5",
        messages=[model_calls.ModelMessage(role="user", content="Return JSON.")],
        model_settings=provider_settings.ModelSettings(),
        proposal_schema=proposal_schema.derive_proposal_schema(MixedEnumProposal),
    )
    sdk_client = fake_sdk_clients.FakeAnthropicClient()
    client = provider_client.LlmClient(sdk_clients={"anthropic": sdk_client})

    with pytest.raises(model_calls.ModelError) as info:
        asyncio.run(client.invoke(request))

    assert info.value.kind == "invalid_payload"
    assert info.value.retryable is False
    assert "MixedEnumProposal" in info.value.message
    identity = info.value.identity
    assert identity is not None
    assert identity.provider == "anthropic"
    assert [attempt.status for attempt in info.value.attempts] == ["failure"]
    assert sdk_client.calls == []
