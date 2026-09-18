"""Protect the Perplexity Agent API request and response boundary."""

from __future__ import annotations

import asyncio
import types
import typing

import perplexity
import pytest

import sergent_py_providers.perplexity_agent as perplexity_agent


class _Responses:
    """Record Agent API calls and return one scripted response."""

    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    async def create(self, **kwargs: object) -> object:
        """Return the configured response after recording request fields."""
        self.calls.append(kwargs)
        return self.response


class _SdkClient:
    """Expose the narrow official SDK surface used by the transport."""

    def __init__(self, response: object) -> None:
        self.responses = _Responses(response)


def _response(
    *,
    status: str = "completed",
    output_text: str = "Complete report.",
    error: object = None,
) -> types.SimpleNamespace:
    """Build one provider response shape admitted by the transport boundary."""
    return types.SimpleNamespace(status=status, output_text=output_text, error=error)


def test_research_sends_only_medium_preset_and_plain_input() -> None:
    """The transport must preserve plain report text and the minimal request shape."""
    sdk = _SdkClient(_response(output_text="  Complete report with citations.  "))
    client = perplexity_agent.PerplexityAgentClient(sdk_client=sdk)

    report = asyncio.run(client.research("Research this exact input."))

    assert report == "  Complete report with citations.  "
    assert sdk.responses.calls == [{"preset": "medium", "input": "Research this exact input."}]


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (
            _response(
                status="failed",
                output_text="Partial text must not pass.",
                error=types.SimpleNamespace(message="provider failed"),
            ),
            "response status was failed: provider failed",
        ),
        (_response(output_text=" \n "), "response had no text output"),
    ],
)
def test_research_rejects_non_completed_or_empty_responses(
    response: object,
    message: str,
) -> None:
    """Partial and empty external responses must fail at their real boundary."""
    client = perplexity_agent.PerplexityAgentClient(sdk_client=_SdkClient(response))

    with pytest.raises(RuntimeError, match=message):
        asyncio.run(client.research("Research this."))


def test_owned_client_uses_credential_timeout_and_no_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Normal construction must apply the documented bounded transport policy."""
    constructed: list[dict[str, typing.Any]] = []
    closed = 0

    class _OwnedSdkClient(_SdkClient):
        """Capture official client construction and context cleanup."""

        def __init__(self, **kwargs: typing.Any) -> None:
            constructed.append(kwargs)
            super().__init__(_response())

        async def close(self) -> None:
            """Record cleanup of the package-owned SDK client."""
            nonlocal closed
            closed += 1

    monkeypatch.setenv("PERPLEXITY_API_KEY", "test-key")
    monkeypatch.setattr(perplexity, "AsyncPerplexity", _OwnedSdkClient)

    async def exercise() -> None:
        """Use the public context lifecycle once."""
        async with perplexity_agent.PerplexityAgentClient() as client:
            assert await client.research("Research this.") == "Complete report."

    asyncio.run(exercise())

    assert constructed == [{"api_key": "test-key", "max_retries": 0, "timeout": 900}]
    assert closed == 1


def test_owned_client_requires_perplexity_credentials() -> None:
    """Normal construction must fail instead of installing a fake fallback."""
    with pytest.raises(RuntimeError, match="PERPLEXITY_API_KEY is not set"):
        perplexity_agent.PerplexityAgentClient()
