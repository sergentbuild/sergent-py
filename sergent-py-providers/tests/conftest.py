from __future__ import annotations

import asyncio

import anthropic
import google.genai as genai
import openai
import perplexity
import pytest

import sergent_py_providers.transports as transports


@pytest.fixture(autouse=True)
def _block_live_provider_access(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in transports.CREDENTIAL_ENV_VARS:
        monkeypatch.delenv(name, raising=False)

    class DeniedSdkClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            del args, kwargs
            raise AssertionError("tests must not create live SDK clients")

    monkeypatch.setattr(openai, "AsyncOpenAI", DeniedSdkClient)
    monkeypatch.setattr(anthropic, "AsyncAnthropic", DeniedSdkClient)
    monkeypatch.setattr(genai, "Client", DeniedSdkClient)
    monkeypatch.setattr(perplexity, "AsyncPerplexity", DeniedSdkClient)

    async def denied_command(*args: object, **kwargs: object) -> None:
        raise AssertionError("tests must inject the Ollama command runner")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", denied_command)
