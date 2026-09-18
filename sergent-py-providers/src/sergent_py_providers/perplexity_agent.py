"""Provide the official async Perplexity Agent API research transport.

@sergent/docs/trust-boundaries.md
@sergent-py-providers/docs/KNOWLEDGE.md
"""

from __future__ import annotations

import os
import types
import typing

import perplexity

_PRESET = "medium"
_TIMEOUT_SECONDS = 900


class PerplexityAgentClient:
    """Return complete plain-text research with no transport retries.

    @sergent-py-providers/docs/KNOWLEDGE.md
    """

    def __init__(self, *, sdk_client: typing.Any = None) -> None:
        self._owns_client = sdk_client is None
        self._client = sdk_client if sdk_client is not None else _make_client()

    async def __aenter__(self) -> PerplexityAgentClient:
        """Share one SDK client across a bounded research batch."""
        return self

    async def __aexit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _traceback: types.TracebackType | None,
    ) -> None:
        """Close only the SDK client this transport constructed."""
        if self._owns_client:
            await self._client.close()

    async def research(self, input_text: str, /) -> str:
        """Return report text only from a completed Agent API response."""
        response = await self._client.responses.create(preset=_PRESET, input=input_text)
        if response.status != "completed":
            detail = "" if response.error is None else f": {response.error.message}"
            raise RuntimeError(f"Perplexity Agent response status was {response.status}{detail}")
        report = response.output_text
        if not report.strip():
            raise RuntimeError("Perplexity Agent response had no text output")
        return report


def _make_client() -> perplexity.AsyncPerplexity:
    """Construct the official SDK client from the owned credential."""
    key = os.environ.get("PERPLEXITY_API_KEY")
    if not key:
        raise RuntimeError("PERPLEXITY_API_KEY is not set")
    return perplexity.AsyncPerplexity(
        api_key=key,
        max_retries=0,
        timeout=_TIMEOUT_SECONDS,
    )
