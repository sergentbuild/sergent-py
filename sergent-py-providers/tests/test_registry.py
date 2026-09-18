"""Registry integrity for curated provider adapters."""

from __future__ import annotations

import dataclasses

import sergent_py_providers.client as provider_client
import sergent_py_providers.facts as provider_facts


def test_registry_contains_only_curated_provider_adapters() -> None:
    assert tuple(provider_client._ADAPTERS) == (
        "openai",
        "anthropic",
        "gemini",
        "ollama",
    )
    for provider, adapter in provider_client._ADAPTERS.items():
        assert adapter.sdk_package
        assert callable(adapter.make_client)
        assert callable(adapter.invoke)
        selection = provider_client._select_model(f"{provider}/org/model:tag")
        assert selection.provider == provider
        assert selection.adapter is adapter
        identity = provider_facts._model_identity(selection)
        assert identity.provider == provider
        assert identity.model == "org/model:tag"


def test_provider_adapter_has_only_provider_level_fields() -> None:
    fields = {field.name for field in dataclasses.fields(provider_client._ProviderAdapter)}
    assert fields == {
        "sdk_package",
        "make_client",
        "invoke",
        "status_errors",
        "local_model_preflight",
    }


def test_ollama_provider_facts_are_owned_by_its_adapter() -> None:
    adapter = provider_client._ADAPTERS["ollama"]
    assert adapter.local_model_preflight is True
    assert adapter.status_error_kind(400) == "invalid_payload"
    assert adapter.status_error_kind(422) == "invalid_payload"
    assert adapter.status_error_kind(404) == "model_not_found"
    assert adapter.status_error_kind(429) is None
