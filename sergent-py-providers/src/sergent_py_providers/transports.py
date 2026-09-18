"""Adapt core model calls to official provider SDKs.
@sergent/docs/trust-boundaries.md
@sergent-py-providers/docs/KNOWLEDGE.md"""

from __future__ import annotations

import inspect
import os
import time
import typing

import anthropic
import google.genai as genai
import google.genai.errors as genai_errors
import google.genai.types as genai_types
import httpx
import openai

import sergent_py_core.model_calls as core_model_calls
import sergent_py_providers.facts as facts
import sergent_py_providers.message_shapes as shapes
import sergent_py_providers.settings as settings

if typing.TYPE_CHECKING:
    import sergent_py_providers.client as pc

_ANTHROPIC_DEFAULT_MAX_TOKENS = 4096
_OLLAMA_API_KEY = "ollama"

_OLLAMA_THINK = {"low": False, "medium": True, "high": True}

# The Gemini SDK raises the HTTP client's own timeout and connection errors unwrapped.
_SDK_ERROR_TYPES = (
    openai.APIError,
    anthropic.APIError,
    genai_errors.APIError,
    httpx.TimeoutException,
    httpx.ConnectError,
)


def _tokens(inp: typing.Any, out: typing.Any) -> dict[str, int] | None:
    """Retain each token count that the provider reports.
    @sergent/docs/observability.md
    @sergent-py-providers/docs/KNOWLEDGE.md"""
    tokens: dict[str, int] = {}
    if inp is not None:
        tokens["input"] = int(inp)
    if out is not None:
        tokens["output"] = int(out)
    return tokens or None


def _settings(request: core_model_calls.ModelRequest) -> settings.ModelSettings:
    """Require provider-owned settings before any SDK access.
    @sergent-py-providers/docs/KNOWLEDGE.md"""
    if not isinstance(request.model_settings, settings.ModelSettings):
        raise core_model_calls.ModelError(
            "provider_error", "model_settings must be a ModelSettings object"
        )
    return request.model_settings


# Every environment variable an adapter client factory consults. Test conftests derive their
# env deny-lists from this tuple; a new provider's variables must be added here.
CREDENTIAL_ENV_VARS = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "OLLAMA_API_KEY",
    "SERGENT_OLLAMA_BASE_URL",
    "PERPLEXITY_API_KEY",
)


def _openai_client(timeout_seconds: int | None) -> object:
    """Construct an official OpenAI SDK client from owned credentials.
    @sergent/docs/trust-boundaries.md
    @sergent-py-providers/docs/providers.md"""
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise core_model_calls.ModelError("missing_credentials", "OPENAI_API_KEY is not set")
    kwargs: dict[str, typing.Any] = {"api_key": key, "max_retries": 0}
    if timeout_seconds is not None:
        kwargs["timeout"] = timeout_seconds
    return openai.AsyncOpenAI(**kwargs)


def _anthropic_client(timeout_seconds: int | None) -> object:
    """Construct an official Anthropic SDK client from owned credentials.
    @sergent/docs/trust-boundaries.md
    @sergent-py-providers/docs/providers.md"""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise core_model_calls.ModelError("missing_credentials", "ANTHROPIC_API_KEY is not set")
    kwargs: dict[str, typing.Any] = {"api_key": key, "max_retries": 0}
    if timeout_seconds is not None:
        kwargs["timeout"] = timeout_seconds
    return anthropic.AsyncAnthropic(**kwargs)


def _gemini_client(timeout_seconds: int | None) -> object:
    """Construct an official Gemini SDK client from owned credentials.
    @sergent/docs/trust-boundaries.md
    @sergent-py-providers/docs/providers.md"""
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise core_model_calls.ModelError("missing_credentials", "GEMINI_API_KEY is not set")
    retry_options = genai_types.HttpRetryOptions(attempts=1)
    http_options = genai_types.HttpOptions(
        timeout=None if timeout_seconds is None else timeout_seconds * 1000,
        retry_options=retry_options,
    )
    return genai.Client(api_key=key, http_options=http_options)


def _ollama_client(timeout_seconds: int | None) -> object:
    """Construct an OpenAI-compatible Ollama SDK client from its endpoint facts.
    @sergent/docs/trust-boundaries.md
    @sergent-py-providers/docs/providers.md"""
    base = os.environ.get("SERGENT_OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    if base.endswith("/api"):
        raise core_model_calls.ModelError(
            "provider_error", "SERGENT_OLLAMA_BASE_URL must not end in /api"
        )
    kwargs: dict[str, typing.Any] = {
        "api_key": os.environ.get("OLLAMA_API_KEY", _OLLAMA_API_KEY),
        "base_url": f"{base}/v1/",
        "max_retries": 0,
    }
    if timeout_seconds is not None:
        kwargs["timeout"] = timeout_seconds
    return openai.AsyncOpenAI(**kwargs)


async def _close_client(client: typing.Any) -> None:
    """Close a package-created SDK client through its supported hook."""
    close = getattr(client, "close", None) or getattr(client, "aclose", None)
    if close is None:
        return
    result = close()
    if inspect.isawaitable(result):
        await result


def _openai_output_text(response: typing.Any) -> str:
    """Require usable text from an OpenAI response."""
    output_text = response.output_text
    if not output_text:
        raise core_model_calls.ModelError("invalid_response", "OpenAI response had no text output")
    return str(output_text)


def _openai_refusal(response: typing.Any) -> str | None:
    """Return the first documented refusal block from an OpenAI message."""
    for output in response.output:
        if output.type != "message":
            continue
        for block in output.content:
            if block.type == "refusal":
                return str(block.refusal)
    return None


def _openai_envelope_text(response: typing.Any, refusal: str | None) -> str | None:
    """Retain available OpenAI text before proposal parsing."""
    if response.output_text:
        return str(response.output_text)
    return refusal


def _anthropic_output_text(response: typing.Any) -> str:
    """Join usable Anthropic text blocks or reject an empty response."""
    chunks = [block.text for block in response.content if block.type == "text" and block.text]
    if not chunks:
        raise core_model_calls.ModelError(
            "invalid_response", "Anthropic response had no text output"
        )
    return "\n".join(str(chunk) for chunk in chunks)


def _anthropic_envelope_text(response: typing.Any) -> str | None:
    """Retain available Anthropic text before proposal parsing."""
    chunks = [str(block.text) for block in response.content if block.type == "text" and block.text]
    return "\n".join(chunks) or None


def _gemini_output_text(response: typing.Any) -> str:
    """Require usable text from a Gemini response."""
    text = response.text
    if not text:
        raise core_model_calls.ModelError("invalid_response", "Gemini response had no text output")
    return str(text)


def _ollama_output_text(response: typing.Any) -> str:
    """Require usable assistant text from an Ollama-compatible response."""
    try:
        message = response.choices[0].message
    except (TypeError, IndexError) as exc:
        raise core_model_calls.ModelError(
            "invalid_response", "Ollama response had no text output"
        ) from exc
    content = message.content
    if not content:
        raise core_model_calls.ModelError("invalid_response", "Ollama response had no text output")
    return str(content)


def _usage(usage: typing.Any, input_field: str, output_field: str) -> dict | None:
    """Normalize SDK usage fields into model-call token facts.
    @sergent-py-providers/docs/KNOWLEDGE.md"""
    return _tokens(getattr(usage, input_field, None), getattr(usage, output_field, None))


def _text_response(
    selection: pc._ModelSelection,
    raw_response: typing.Any,
    output_text: typing.Callable[[typing.Any], str],
    *,
    usage: core_model_calls.CallUsage,
) -> core_model_calls.ModelResponse:
    """Build call evidence while preserving usage when text extraction fails.
    @sergent-py-providers/docs/KNOWLEDGE.md"""
    identity = facts._model_identity(selection)
    try:
        output = output_text(raw_response)
    except core_model_calls.ModelError as exc:
        response = core_model_calls.ModelResponse(identity=identity, usage=usage)
        raise core_model_calls.ModelError(
            exc.kind,
            exc.message,
            retryable=exc.retryable,
            response=response,
        ) from exc
    return core_model_calls.ModelResponse(identity=identity, raw_output=output, usage=usage)


def _partial_response(
    selection: pc._ModelSelection,
    usage: core_model_calls.CallUsage,
    raw_output: str | None,
) -> core_model_calls.ModelResponse:
    """Build partial evidence for a documented HTTP-success failure."""
    return core_model_calls.ModelResponse(
        identity=facts._model_identity(selection),
        raw_output=raw_output,
        usage=usage,
    )


def _check_openai_envelope(
    response: typing.Any,
    partial: core_model_calls.ModelResponse,
    refusal: str | None,
) -> None:
    """Contain documented OpenAI incomplete and refusal envelopes."""
    if response.status == "incomplete":
        reason = response.incomplete_details.reason
        raise core_model_calls.ModelError(
            "invalid_response",
            f"OpenAI response was incomplete: {reason}",
            response=partial,
        )
    if refusal is not None:
        raise core_model_calls.ModelError(
            "invalid_response",
            f"OpenAI response was refused: {refusal}",
            response=partial,
        )


def _check_anthropic_envelope(
    response: typing.Any,
    partial: core_model_calls.ModelResponse,
) -> None:
    """Contain documented Anthropic refusal and max-token envelopes."""
    if response.stop_reason == "refusal":
        raise core_model_calls.ModelError(
            "invalid_response",
            "Anthropic response was refused",
            response=partial,
        )
    if response.stop_reason == "max_tokens":
        raise core_model_calls.ModelError(
            "invalid_response",
            "Anthropic response was incomplete: max_tokens",
            response=partial,
        )


async def _call_openai(
    selection: pc._ModelSelection,
    request: core_model_calls.ModelRequest,
    client: typing.Any,
) -> core_model_calls.ModelResponse:
    """Invoke OpenAI Responses with native Proposal Schema encoding and measured evidence.
    @sergent-py-providers/docs/KNOWLEDGE.md"""
    t0 = time.perf_counter()
    settings = _settings(request)
    kwargs: dict[str, typing.Any] = {
        "model": selection.model,
        "input": shapes._openai_messages(request),
        "reasoning": {"effort": settings.thinking_effort},
        "text": {
            "format": {
                "type": "json_schema",
                "name": request.proposal_schema.name,
                "schema": request.proposal_schema.json_schema,
                "strict": True,
            }
        },
    }
    if settings.max_output_tokens is not None:
        kwargs["max_output_tokens"] = settings.max_output_tokens
    response = await client.responses.create(**kwargs)
    usage = core_model_calls.CallUsage(
        latency_ms=int((time.perf_counter() - t0) * 1000),
        tokens=_usage(response.usage, "input_tokens", "output_tokens"),
        request_id=response.id or getattr(response, "_request_id", None),
    )
    refusal = _openai_refusal(response)
    partial = _partial_response(selection, usage, _openai_envelope_text(response, refusal))
    _check_openai_envelope(response, partial, refusal)
    return _text_response(selection, response, _openai_output_text, usage=usage)


async def _call_anthropic(
    selection: pc._ModelSelection,
    request: core_model_calls.ModelRequest,
    client: typing.Any,
) -> core_model_calls.ModelResponse:
    """Invoke Anthropic Messages with adaptive thinking and measured evidence.
    @sergent-py-providers/docs/KNOWLEDGE.md"""
    system, messages = shapes._anthropic_messages(request)
    t0 = time.perf_counter()
    settings = _settings(request)
    try:
        lowered_schema = anthropic.transform_schema(request.proposal_schema.json_schema)
    except ValueError as exc:
        raise core_model_calls.ModelError(
            "invalid_payload",
            f"Anthropic schema lowering rejected {request.proposal_schema.name}: {exc}",
        ) from exc
    response = await client.messages.create(
        model=selection.model,
        max_tokens=settings.max_output_tokens or _ANTHROPIC_DEFAULT_MAX_TOKENS,
        system=system,
        messages=messages,
        thinking={"type": "adaptive"},
        output_config={
            "effort": settings.thinking_effort,
            "format": {
                "type": "json_schema",
                "schema": lowered_schema,
            },
        },
    )
    usage = core_model_calls.CallUsage(
        latency_ms=int((time.perf_counter() - t0) * 1000),
        tokens=_usage(response.usage, "input_tokens", "output_tokens"),
        request_id=response.id or getattr(response, "_request_id", None),
    )
    partial = _partial_response(selection, usage, _anthropic_envelope_text(response))
    _check_anthropic_envelope(response, partial)
    return _text_response(selection, response, _anthropic_output_text, usage=usage)


async def _call_gemini(
    selection: pc._ModelSelection,
    request: core_model_calls.ModelRequest,
    client: typing.Any,
) -> core_model_calls.ModelResponse:
    """Invoke Gemini generate-content with native Proposal Schema encoding and measured evidence.
    @sergent-py-providers/docs/KNOWLEDGE.md"""
    system, contents = shapes._gemini_contents(request)
    t0 = time.perf_counter()
    settings = _settings(request)
    response = await client.aio.models.generate_content(
        model=selection.model,
        contents=contents,
        config=genai_types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=settings.max_output_tokens,
            response_mime_type="application/json",
            response_json_schema=request.proposal_schema.json_schema,
            automatic_function_calling=genai_types.AutomaticFunctionCallingConfig(disable=True),
        ),
    )
    return _text_response(
        selection,
        response,
        _gemini_output_text,
        usage=core_model_calls.CallUsage(
            latency_ms=int((time.perf_counter() - t0) * 1000),
            tokens=_usage(
                response.usage_metadata,
                "prompt_token_count",
                "candidates_token_count",
            ),
            request_id=response.response_id,
        ),
    )


async def _call_ollama(
    selection: pc._ModelSelection,
    request: core_model_calls.ModelRequest,
    client: typing.Any,
) -> core_model_calls.ModelResponse:
    """Invoke Ollama chat with mapped thinking and measured evidence.
    @sergent-py-providers/docs/KNOWLEDGE.md"""
    t0 = time.perf_counter()
    settings = _settings(request)
    kwargs: dict[str, typing.Any] = {
        "model": selection.model,
        "messages": shapes._ollama_messages(request),
        "extra_body": {"think": _OLLAMA_THINK[settings.thinking_effort]},
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": request.proposal_schema.name,
                "schema": request.proposal_schema.json_schema,
                "strict": True,
            },
        },
    }
    if settings.max_output_tokens is not None:
        kwargs["max_tokens"] = settings.max_output_tokens
    response = await client.chat.completions.create(**kwargs)
    return _text_response(
        selection,
        response,
        _ollama_output_text,
        usage=core_model_calls.CallUsage(
            latency_ms=int((time.perf_counter() - t0) * 1000),
            tokens=_usage(response.usage, "prompt_tokens", "completion_tokens")
            or _tokens(
                getattr(response, "prompt_eval_count", None),
                getattr(response, "eval_count", None),
            ),
            request_id=None,
        ),
    )


async def _run_call(
    selection: pc._ModelSelection,
    request: core_model_calls.ModelRequest,
    *,
    sdk_client: typing.Any = None,
) -> core_model_calls.ModelResponse:
    """Dispatch through the selected adapter, closing only package-created clients.
    @sergent-py-providers/docs/KNOWLEDGE.md"""
    client = sdk_client
    created_client = client is None
    if client is None:
        client = selection.adapter.make_client(_settings(request).timeout_seconds)

    try:
        return await selection.adapter.invoke(selection, request, client)
    finally:
        if created_client:
            await _close_client(client)
